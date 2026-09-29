"""Orchestration : zone series -> indicateurs -> alertes -> encadrés -> data/latest.json"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import llm
from .metrics import compute_metrics, current_stages, evaluate_zone, risk_score

ROOT = Path(__file__).resolve().parent.parent


def calm_bulletin(zone: dict, m: dict, stages: list[dict]) -> str:
    st = ", ".join(f'{c["etape"].lower()} ({c["culture"]})' for c in stages) or "hors période sensible"
    t = m["tx_fc7_anom"]
    if t is None:
        temp = f'maximales jusqu\'à {m["tx_fc7_max"]} °C'.replace(".", ",")
    elif abs(t) < 1.5:
        temp = "températures proches des normales"
    else:
        temp = f'températures {abs(t):.1f} °C {"au-dessus" if t > 0 else "en dessous"} des normales'.replace(".", ",")
    if m["pr_obs30_normal"] is not None and m["pr_obs30_normal"] >= 15 and m["pr_obs30_pct"] is not None:
        pluie = f'pluie des 30 derniers jours à {m["pr_obs30_pct"]} % de la normale'
    elif m["pr_obs30_normal"] is None:
        pluie = f'{m["pr_obs30_mm"]} mm de pluie en 30 jours'
    else:
        pluie = "saison sèche par nature"
    return f"Aucun seuil critique franchi. Stade actuel : {st}. Semaine à venir : {temp} ; {pluie}."


def build(zones: list[dict], series: dict, today: date, meta: dict,
          use_llm: bool = True, encadres_override: dict | None = None) -> dict:
    out_zones, alerts_feed = [], []
    for z in zones:
        s = series[z["id"]]
        m = compute_metrics(s)
        stages = current_stages(z, today.month)
        alerts = evaluate_zone(z, m, today)
        score = risk_score(m, alerts, stages)
        encadre = None
        if alerts:
            payload = llm.build_payload(z, m, alerts, stages, today.isoformat())
            if encadres_override and z["id"] in encadres_override:
                encadre = encadres_override[z["id"]]
            elif use_llm:
                encadre = llm.generate(payload)
            else:
                encadre = llm.template(payload)
            encadre["alerte_id"] = alerts[0]["id"]
            for a in alerts:
                alerts_feed.append({"zone": z["id"], "nom": z["nom"], "pays": z["pays"],
                                    "culture": a["culture"], "phenomene": a["phenomene"],
                                    "severite": a["severite"], "niveau": a["niveau"],
                                    "contrat": a["contrat"], "direction": a["direction"]})
        m.pop("_fc10_tx", None)
        out_zones.append({
            **{k: z[k] for k in ("id", "nom", "pays", "continent", "cultures", "contrats",
                                 "poids_mondial", "points", "calendrier", "regles")},
            "stades": stages, "metriques": m, "alertes": alerts, "score": score,
            "encadre": encadre, "bulletin": None if alerts else calm_bulletin(z, m, stages),
            "series": {k: s[k] for k in ("tx", "tn", "pr", "et0", "ntx", "ntn", "npr")},
            "clim": {k: s[k] for k in ("sdtx", "clim_pr_obs30", "clim_pr_fc14")},
        })
    alerts_feed.sort(key=lambda a: -a["severite"])
    time0 = series[zones[0]["id"]]["time"]
    return {
        "genere_le": meta.get("generated") or datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "date_du_jour": today.isoformat(), "time": time0, "i0": series[zones[0]["id"]]["i0"],
        "sources": meta.get("sources", []), "couverture_normales": meta.get("coverage"),
        "system_prompt": llm.SYSTEM_PROMPT, "zones": out_zones, "alertes": alerts_feed,
    }


def write_outputs(data: dict, normals: dict | None = None) -> None:
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    if normals is not None:
        (ROOT / "data" / "normals.json").write_text(json.dumps(normals, separators=(",", ":")))
