"""Backtest des règles sur 1991-2020 avec l'historique ERA5 déjà téléchargé pour les normales.

Pour chaque jour de 1991 à 2020, on calcule les mêmes indicateurs que le moteur du jour, en
remplaçant les prévisions par ce qui s'est réellement passé (prévision parfaite). On regarde
ensuite, pour chaque règle et chaque année, si elle se serait déclenchée et à quel niveau.

Sorties (data/backtest.json) :
- par règle : années de déclenchement, fréquence, premier jour, niveau maximal ;
- par zone : niveau maximal atteint chaque année ;
- vérification sur une liste de chocs connus (config/evenements.json).
Limite connue : les normales incluent l'année testée (échantillon de référence non exclu).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .aggregate import doy, zone_value, _zone_points
from .fetch import YEARS, all_points, load_raw, point_key

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "backtest.json"
MIN_NORMAL_MM = 15
MIN_YEARS_OK = 25  # années évaluables minimum pour publier le résultat d'une règle

OPS = {"<": lambda v, t: v < t, ">": lambda v, t: v > t, ">=": lambda v, t: v >= t, "<=": lambda v, t: v <= t}


def _series(raw, zp, days):
    out = {"tx": [], "tn": [], "pr": []}
    for d in days:
        dd = 28 if (d.month, d.day) == (2, 29) else d.day
        for vi, k in enumerate(("tx", "tn", "pr")):
            out[k].append(zone_value(raw, zp, vi, d.year, d.month, dd))
    return out


def _window_ok(arr, a, b):
    return a >= 0 and b <= len(arr) and all(arr[i] is not None for i in range(a, b))


def _value(rule, s, npr, i):
    """Valeur de l'indicateur de la règle au jour i (index dans la série continue)."""
    m = rule["metrique"]
    if m == "pr_obs30_pct" or m == "pr_fc14_pct":
        a, b = (i - 30, i) if m == "pr_obs30_pct" else (i, i + 14)
        if not _window_ok(s["pr"], a, b) or any(npr[j] is None for j in range(a, b)):
            return None
        normal = sum(npr[j] for j in range(a, b))
        if normal < MIN_NORMAL_MM:
            return None
        return 100 * sum(s["pr"][a:b]) / normal
    if m == "tn_fc7_min":
        return min(s["tn"][i:i + 7]) if _window_ok(s["tn"], i, i + 7) else None
    if m == "tx_fc7_max":
        return max(s["tx"][i:i + 7]) if _window_ok(s["tx"], i, i + 7) else None
    if m == "n_tx_gt":
        return sum(1 for x in s["tx"][i:i + 10] if x > rule["t"]) if _window_ok(s["tx"], i, i + 10) else None
    return None


def run(zones: list[dict], normals: dict, log=print) -> dict:
    raw = {}
    for _, lat, lon, _ in all_points(zones):
        k = point_key(lat, lon)
        if k not in raw:
            raw[k] = load_raw(k)
    start, end = date(YEARS[0], 1, 1), date(YEARS[-1], 12, 31)
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    res_rules, res_zones, ev_cache = {}, {}, {}
    for z in zones:
        zp = _zone_points(z)
        s = _series(raw, zp, days)
        nz = normals.get(z["id"], {})
        npr = [nz["npr"][doy(d)] if nz.get("npr") else None for d in days]
        per_year = {y: 0 for y in YEARS}
        for r in z["regles"]:
            fired, evaluable, first, months, ev_months = {}, set(), {}, {}, set()
            hit = OPS[r["op"]]
            for i, d in enumerate(days):
                if d.month not in r["mois"]:
                    continue
                v = _value(r, s, npr, i)
                if v is None:
                    continue
                evaluable.add(d.year)
                ev_months.add((d.year, d.month))
                if hit(v, r["seuil"]):
                    sev = r["severite"]
                    if r.get("severe") is not None and hit(v, r["severe"]):
                        sev = min(4, sev + 1)
                    if sev > fired.get(d.year, 0):
                        fired[d.year] = sev
                    first.setdefault(d.year, d.isoformat())
                    months.setdefault(d.year, set()).add(d.month)
            n_ok = len(evaluable)
            res_rules[r["id"]] = {
                "zone": z["id"], "annees_evaluees": n_ok,
                "annees": {str(y): fired[y] for y in sorted(fired)},
                "premier_jour": {str(y): first[y] for y in sorted(first)},
                "mois": {str(y): sorted(months[y]) for y in sorted(months)},
                "frequence": round(100 * len(fired) / n_ok) if n_ok else None,
                "publie": n_ok >= MIN_YEARS_OK,
            }
            ev_cache[r["id"]] = ev_months
            for y, sv in fired.items():
                per_year[y] = max(per_year[y], sv)
        res_zones[z["id"]] = {str(y): v for y, v in per_year.items()}
    events = _check_events(zones, res_rules, ev_cache)
    out = {"periode": f"{YEARS[0]}-{YEARS[-1]}", "methode": "prévision parfaite (observé ERA5), normales 1991-2020",
           "regles": res_rules, "zones": res_zones, "evenements": events}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    ok = [e for e in events if e["detecte"] is not None]
    log(f"Backtest : {len(res_rules)} règles, {sum(1 for e in ok if e['detecte'])}/{len(ok)} chocs connus détectés")
    return out


def _check_events(zones, res_rules, ev_cache):
    path = ROOT / "config" / "evenements.json"
    if not path.exists():
        return []
    evs = json.loads(path.read_text())["evenements"]
    rules_by_zone = {z["id"]: z["regles"] for z in zones}
    out = []
    for e in evs:
        rules = rules_by_zone.get(e["zone"], [])
        months = set(e["mois"])
        cand = [r for r in rules if months & set(r["mois"])]
        # une règle compte si tous les mois de l'événement qu'elle couvre ont des données cette année-là
        evaluated = [r for r in cand if res_rules[r["id"]]["publie"]
                     and all((e["annee"], m) in ev_cache[r["id"]] for m in months & set(r["mois"]))]
        hits = []
        for r in evaluated:
            rr = res_rules[r["id"]]
            sev = rr["annees"].get(str(e["annee"]))
            if sev and set(rr["mois"].get(str(e["annee"]), [])) & months:
                hits.append({"regle": r["id"], "phenomene": r["phenomene"], "severite": sev})
        complete = bool(cand) and len(evaluated) == len(cand)
        out.append({**e, "detecte": (len(hits) > 0) if complete else None, "regles": hits})
    return out
