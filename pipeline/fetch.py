"""Collecte Open-Meteo : prévisions du jour et historique 1991-2020 (normales), dans le respect du quota gratuit.

Quota Open-Meteo (usage non commercial) : ~600 appels/min, ~5 000/h, ~10 000/jour.
Un appel "pèse" : nb_points x max(1, nb_jours / 14). Le poids consommé est suivi dans
data/state/quota.json pour ne jamais dépasser ces limites, même sur plusieurs exécutions.

L'historique est téléchargé mois par mois (le mois en cours et ses voisins d'abord) et
mis en cache dans data/raw/ : une fois complet, plus aucun appel d'archive n'est fait.
"""
from __future__ import annotations

import calendar
import gzip
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PAST_DAYS, FORECAST_DAYS = 30, 16
YEARS = list(range(1991, 2021))
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STATE = ROOT / "data" / "state" / "quota.json"
BUDGET_HOUR, BUDGET_DAY = 4500, 9500  # marge sous les limites 5 000/h et 10 000/jour
PAUSE = 32  # secondes entre deux appels d'archive (limite par minute)


# ---------- points ----------
def all_points(zones: list[dict]) -> list[tuple[str, float, float, float]]:
    return [(z["id"], p[0], p[1], p[2]) for z in zones for p in z["points"]]


def point_key(lat: float, lon: float) -> str:
    return f"{lat:.2f}_{lon:.2f}"


def unique_points(zones: list[dict]) -> list[tuple[float, float]]:
    seen, out = set(), []
    for _, lat, lon, _ in all_points(zones):
        k = point_key(lat, lon)
        if k not in seen:
            seen.add(k)
            out.append((lat, lon))
    return out


# ---------- quota ----------
def weight(n_points: int, n_days: int) -> float:
    return n_points * max(1.0, n_days / 14)


def _load_quota() -> dict:
    now = datetime.now(timezone.utc)
    q = json.loads(STATE.read_text()) if STATE.exists() else {}
    if q.get("day") != now.strftime("%Y-%m-%d"):
        q = {"day": now.strftime("%Y-%m-%d"), "used_day": 0, "hour": now.hour, "used_hour": 0}
    if q.get("hour") != now.hour:
        q["hour"], q["used_hour"] = now.hour, 0
    return q


def _spend(w: float) -> None:
    q = _load_quota()
    q["used_day"] += w
    q["used_hour"] += w
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(q))


def budget_left() -> float:
    q = _load_quota()
    return min(BUDGET_HOUR - q["used_hour"], BUDGET_DAY - q["used_day"])


def _get(url: str, params: dict, w: float, retries: int = 5) -> list:
    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=90)
        if r.status_code == 200:
            _spend(w)
            data = r.json()
            return data if isinstance(data, list) else [data]
        if r.status_code == 429:  # limite atteinte : on arrête proprement, la prochaine exécution reprendra
            raise RuntimeError("quota Open-Meteo atteint : " + r.text[:200])
        time.sleep(10 * (attempt + 1))
    r.raise_for_status()
    return []


# ---------- prévisions ----------
def fetch_forecast(zones: list[dict]) -> dict:
    """{'time': [...], 'points': {point_key: [tx[], tn[], pr[], et0[]]}}"""
    pts = unique_points(zones)
    res = _get(FORECAST_URL, {
        "latitude": ",".join(str(p[0]) for p in pts), "longitude": ",".join(str(p[1]) for p in pts),
        "timezone": "GMT", "models": "best_match",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration",
        "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS,
    }, weight(len(pts), PAST_DAYS + FORECAST_DAYS))
    keys = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum", "et0_fao_evapotranspiration")
    return {"time": res[0]["daily"]["time"],
            "points": {point_key(*p): [r["daily"][k] for k in keys] for p, r in zip(pts, res)}}


# ---------- historique (normales) ----------
def load_raw(key: str) -> dict:
    f = RAW / f"{key}.json.gz"
    return json.loads(gzip.decompress(f.read_bytes())) if f.exists() else {}


def save_raw(key: str, data: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{key}.json.gz").write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode()))


def month_priority(today: date) -> list[int]:
    """Mois en cours, précédent, suivant, puis de plus en plus loin."""
    m = today.month
    prev, nxt = (m - 2) % 12 + 1, m % 12 + 1
    order = [m, nxt, prev] if today.day > 15 else [m, prev, nxt]
    for k in range(2, 7):
        order += [(m + k - 1) % 12 + 1, (m - k - 1) % 12 + 1]
    seen, out = set(), []
    for x in order:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def fill_history(zones: list[dict], today: date, log=print) -> dict:
    """Télécharge ce que le budget permet. Retourne l'état de couverture."""
    pts = unique_points(zones)
    raw = {point_key(*p): load_raw(point_key(*p)) for p in pts}
    stopped = False
    dirty: set[str] = set()

    def flush():
        for k in dirty:
            save_raw(k, raw[k])
        dirty.clear()

    for m in month_priority(today):
        for y in YEARS:
            missing = [p for p in pts if str(y) not in raw[point_key(*p)].get(f"{m:02d}", {})]
            if not missing:
                continue
            ndays = calendar.monthrange(y, m)[1]
            w = weight(len(missing), ndays)
            if w > budget_left():
                stopped = True
                break
            try:
                res = _get(ARCHIVE_URL, {
                    "latitude": ",".join(str(p[0]) for p in missing),
                    "longitude": ",".join(str(p[1]) for p in missing),
                    "start_date": f"{y}-{m:02d}-01", "end_date": f"{y}-{m:02d}-{ndays:02d}",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "timezone": "GMT",
                }, w)
            except RuntimeError as e:
                log(str(e))
                stopped = True
                break
            for p, r in zip(missing, res):
                k = point_key(*p)
                raw[k].setdefault(f"{m:02d}", {})[str(y)] = [
                    r["daily"]["temperature_2m_max"], r["daily"]["temperature_2m_min"], r["daily"]["precipitation_sum"]]
                dirty.add(k)
            log(f"historique {m:02d}/{y} : {len(missing)} points")
            time.sleep(PAUSE)
        flush()  # sauvegarde à la fin de chaque mois (et à l'arrêt)
        if stopped:
            break
    return coverage(zones)


def coverage(zones: list[dict]) -> dict:
    pts = unique_points(zones)
    raw = {point_key(*p): load_raw(point_key(*p)) for p in pts}
    months = {}
    for m in range(1, 13):
        n = sum(1 for p in pts for y in YEARS if str(y) in raw[point_key(*p)].get(f"{m:02d}", {}))
        months[m] = round(100 * n / (len(pts) * len(YEARS)))
    return {"par_mois": months, "global": round(sum(months.values()) / 12)}
