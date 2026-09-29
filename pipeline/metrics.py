"""Indicateurs agro-climatiques, moteur de règles, sévérité et score de risque.

La même logique existe en JavaScript dans dashboard/app.html (recalcul à l'ouverture de la page) :
toute modification ici doit y être reportée.
"""
from __future__ import annotations

from datetime import date
from statistics import mean

SEV_LABELS = {1: "Vigilance", 2: "Alerte", 3: "Alerte élevée", 4: "Alerte critique"}
MIN_NORMAL_MM = 15  # en dessous, saison sèche par nature : pas de règle en % de la normale


def _pct_rank(value, sample):
    if not sample or value is None:
        return None
    below = sum(1 for s in sample if s < value) + 0.5 * sum(1 for s in sample if s == value)
    return round(100 * below / len(sample))


def _r(x, nd=1):
    return None if x is None else round(x, nd)


def compute_metrics(s: dict) -> dict:
    i0 = s["i0"]
    obs30, obs7 = range(i0 - 30, i0), range(i0 - 7, i0)
    fc7, fc10, fc14 = range(i0, i0 + 7), range(i0, i0 + 10), range(i0, i0 + 14)
    v = lambda k, rg: [s[k][i] for i in rg if s[k][i] is not None]

    def anom(k, nk, rg):
        d = [s[k][i] - s[nk][i] for i in rg if s[k][i] is not None and s[nk][i] is not None]
        return mean(d) if len(d) == len(rg) else None

    def normal_sum(rg):
        n = [s["npr"][i] for i in rg]
        return None if any(x is None for x in n) else sum(n)

    pr_obs30, n_obs30 = sum(v("pr", obs30)), normal_sum(obs30)
    pr_fc14, n_fc14 = sum(v("pr", fc14)), normal_sum(fc14)
    tx_fc7_anom = anom("tx", "ntx", fc7)
    m = {
        "tx_obs7_anom": _r(anom("tx", "ntx", obs7)),
        "tx_fc7_anom": _r(tx_fc7_anom),
        "tn_fc7_anom": _r(anom("tn", "ntn", fc7)),
        "tx_fc7_z": _r(tx_fc7_anom / s["sdtx"]) if tx_fc7_anom is not None and s.get("sdtx") else None,
        "tx_fc7_max": _r(max(v("tx", fc7))),
        "tn_fc7_min": _r(min(v("tn", fc7))),
        "pr_obs30_mm": round(pr_obs30), "pr_obs30_normal": _r(n_obs30, 0) if n_obs30 is not None else None,
        "pr_obs30_pct": round(100 * pr_obs30 / n_obs30) if n_obs30 and n_obs30 >= 1 else None,
        "pr_obs30_rank": _pct_rank(pr_obs30, s.get("clim_pr_obs30")),
        "pr_fc14_mm": round(pr_fc14), "pr_fc14_normal": _r(n_fc14, 0) if n_fc14 is not None else None,
        "pr_fc14_pct": round(100 * pr_fc14 / n_fc14) if n_fc14 and n_fc14 >= 1 else None,
        "pr_fc14_rank": _pct_rank(pr_fc14, s.get("clim_pr_fc14")),
        "wb_obs30": round(sum(v("pr", obs30)) - sum(v("et0", obs30))),
        "normales": n_obs30 is not None and n_fc14 is not None and tx_fc7_anom is not None,
    }
    for key in ("pr_obs30_normal", "pr_fc14_normal"):
        if m[key] is not None:
            m[key] = int(m[key])
    m["_fc10_tx"] = v("tx", fc10)
    return m


def metric_value(m: dict, rule: dict):
    key = rule["metrique"]
    if key == "n_tx_gt":
        return sum(1 for t in m["_fc10_tx"] if t > rule["t"])
    if key in ("pr_obs30_pct", "pr_fc14_pct"):
        normal = m[key.replace("_pct", "_normal")]
        if normal is None or normal < MIN_NORMAL_MM:
            return None
    return m.get(key)


def _hit(val, op, thr) -> bool:
    return {"<": val < thr, ">": val > thr, ">=": val >= thr, "<=": val <= thr}[op]


def _confidence(rule: dict) -> tuple[str, str]:
    k = rule["metrique"]
    if "obs" in k:
        return "élevée", "le constat repose sur les 30 derniers jours, déjà écoulés"
    if k == "pr_fc14_pct":
        return "faible", "la pluie prévue au-delà d'une semaine reste très incertaine"
    return "moyenne", "le signal vient des prévisions à 7-10 jours, fiables mais révisables"


def current_stages(zone: dict, month: int) -> list[dict]:
    return [c for c in zone["calendrier"] if month in c["mois"]]


def evaluate_zone(zone: dict, m: dict, today: date) -> list[dict]:
    alerts = []
    for rule in zone["regles"]:
        if today.month not in rule["mois"]:
            continue
        val = metric_value(m, rule)
        if val is None or not _hit(val, rule["op"], rule["seuil"]):
            continue
        sev = rule["severite"]
        if "severe" in rule and _hit(val, rule["op"], rule["severe"]):
            sev = min(4, sev + 1)
        conf, why = _confidence(rule)
        alerts.append({**{k: rule[k] for k in ("id", "culture", "phenomene", "mecanisme", "contrat",
                                                "direction", "horizon", "metrique", "op", "seuil")},
                       "t": rule.get("t"), "valeur": val, "severite": sev,
                       "niveau": SEV_LABELS[sev], "confiance": conf, "confiance_raison": why})
    return sorted(alerts, key=lambda a: -a["severite"])


def risk_score(m: dict, alerts: list[dict], stages: list[dict]) -> int:
    """0-100 : alertes d'abord, sinon tension de fond pondérée par la sensibilité du stade."""
    if alerts:
        base = 22 * alerts[0]["severite"] + 6 * (len(alerts) - 1)
        return min(100, base + min(10, round(abs(m["tx_fc7_z"] or 0) * 3)))
    sens = max([c["niveau"] for c in stages], default=1) / 3
    pr_dev = (abs((m["pr_obs30_pct"] or 100) - 100) / 10
              if m["pr_obs30_normal"] is not None and m["pr_obs30_normal"] >= MIN_NORMAL_MM else 0)
    return min(20, round(sens * (3 * abs(m["tx_fc7_anom"] or 0) + pr_dev)))
