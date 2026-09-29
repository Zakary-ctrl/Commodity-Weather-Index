"""Commodity Weather Index - point d'entrée.

    python run.py auto     # ce que fait GitHub Actions chaque heure : complète l'historique dans la
                           # limite du quota, puis recalcule tout si c'est l'heure du calcul quotidien
                           # ou si de nouvelles normales sont disponibles
    python run.py daily    # recalcul complet immédiat (prévisions + alertes + encadrés)
    python run.py fill     # complète seulement l'historique 1991-2020 (normales)
    options : --no-llm (encadrés par gabarit), --force (recalcul même si rien n'a changé)

Puis : python make_dashboard.py, et ouvrir site/index.html.
"""
import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.aggregate import build_normals, build_zone_series
from pipeline.build import build, write_outputs
from pipeline.fetch import coverage, fetch_forecast, fill_history

ROOT = Path(__file__).resolve().parent
DAILY_HOUR_UTC = 5
SOURCES = ["Open-Meteo Forecast API (sélection automatique : ECMWF IFS, GFS, ICON...)",
           "Open-Meteo Historical API (ERA5 / ERA5-Land), normales 1991-2020"]


def load_zones():
    return json.loads((ROOT / "config" / "zones.json").read_text())["zones"]


def daily(zones, use_llm=True):
    cov = coverage(zones)
    print(f"Normales disponibles : {cov['global']} % de l'année")
    normals = build_normals(zones)
    fc = fetch_forecast(zones)
    series = build_zone_series(zones, fc, normals)
    today = date.fromisoformat(fc["time"][30])
    data = build(zones, series, today, {"sources": SOURCES, "coverage": cov}, use_llm=use_llm)
    write_outputs(data, normals)
    print(f"OK : {len(data['zones'])} zones, {len(data['alertes'])} alerte(s).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="daily", choices=["auto", "daily", "fill"])
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    zones = load_zones()
    now = datetime.now(timezone.utc)

    if args.mode in ("auto", "fill"):
        full = lambda c: {m for m, v in c["par_mois"].items() if v == 100}
        c0 = coverage(zones)
        c1 = fill_history(zones, now.date())
        print(f"Historique : {c0['global']} % -> {c1['global']} %")
        new_month = len(full(c1)) > len(full(c0))
        if args.mode == "fill":
            return
        latest = ROOT / "data" / "latest.json"
        age_h = 99
        if latest.exists():
            prev = json.loads(latest.read_text())
            age_h = (now - datetime.fromisoformat(prev["genere_le"].replace("Z", "+00:00"))).total_seconds() / 3600
            if [z["id"] for z in prev["zones"]] != [z["id"] for z in zones]:
                age_h = 99  # la configuration des zones a changé : recalcul immédiat
        if not (args.force or new_month or now.hour == DAILY_HOUR_UTC or age_h > 23):
            print("Rien à recalculer pour l'instant.")
            return
    daily(zones, use_llm=not args.no_llm)


if __name__ == "__main__":
    main()
