"""Points -> zones : normales journalières 1991-2020 et séries de la fenêtre courante.

normals.json : pour chaque zone, 366 valeurs (calendrier bissextile, 1er janv. = 0) de
Tmax, Tmin, pluie moyennes (lissées sur +/- 7 jours) et écarts-types de Tmax, Tmin.
Une valeur est None tant que moins de MIN_YEARS années complètes sont disponibles.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean, pstdev

from .fetch import PAST_DAYS, YEARS, all_points, load_raw, point_key

SMOOTH, MIN_YEARS = 7, 25
REF = date(2000, 1, 1)  # année bissextile de référence


def doy(d: date) -> int:
    return (date(2000, d.month, d.day) - REF).days


def _r(x, nd=1):
    return None if x is None else round(x, nd)


def _zone_points(zone):
    return [(point_key(p[0], p[1]), p[2]) for p in zone["points"]]


def zone_value(raw: dict, zone_pts, var: int, y: int, m: int, d: int):
    """Moyenne pondérée des points de la zone pour un jour donné, None si une donnée manque."""
    s = sw = 0.0
    for k, w in zone_pts:
        arr = raw[k].get(f"{m:02d}", {}).get(str(y))
        if arr is None or d - 1 >= len(arr[var]) or arr[var][d - 1] is None:
            return None
        s += arr[var][d - 1] * w
        sw += w
    return s / sw


def _smooth_circ(vals):
    n, out = len(vals), []
    for i in range(n):
        if vals[i] is None:
            out.append(None)
            continue
        win = [vals[(i + k) % n] for k in range(-SMOOTH, SMOOTH + 1)]
        win = [v for v in win if v is not None]
        out.append(mean(win))
    return out


def build_normals(zones: list[dict]) -> dict:
    raw = {}
    for _, lat, lon, _ in all_points(zones):
        k = point_key(lat, lon)
        if k not in raw:
            raw[k] = load_raw(k)
    out = {}
    for z in zones:
        zp = _zone_points(z)
        cols = {v: [] for v in ("tx", "tn", "pr", "sdtx", "sdtn")}
        for i in range(366):
            dd = REF + timedelta(i)
            m, d = dd.month, dd.day
            if (m, d) == (2, 29):
                m, d = 2, 28
            per = {v: [] for v in range(3)}
            for y in YEARS:
                vals = [zone_value(raw, zp, v, y, m, d) for v in range(3)]
                if None not in vals:
                    for v in range(3):
                        per[v].append(vals[v])
            ok = len(per[0]) >= MIN_YEARS
            cols["tx"].append(mean(per[0]) if ok else None)
            cols["tn"].append(mean(per[1]) if ok else None)
            cols["pr"].append(mean(per[2]) if ok else None)
            cols["sdtx"].append(pstdev(per[0]) if ok else None)
            cols["sdtn"].append(pstdev(per[1]) if ok else None)
        out[z["id"]] = {
            "ntx": [_r(v) for v in _smooth_circ(cols["tx"])],
            "ntn": [_r(v) for v in _smooth_circ(cols["tn"])],
            "npr": [_r(v, 2) for v in _smooth_circ(cols["pr"])],
            "sdtx": [_r(v, 2) for v in _smooth_circ(cols["sdtx"])],
            "sdtn": [_r(v, 2) for v in _smooth_circ(cols["sdtn"])],
        }
    return out


def _wmean(values, weights):
    pairs = [(v, w) for v, w in zip(values, weights) if v is not None]
    return sum(v * w for v, w in pairs) / sum(w for _, w in pairs) if pairs else None


def _yearly_sums(raw, zp, dates: list[date]) -> list[float]:
    """Cumul de pluie de la zone sur les mêmes jours calendaires, pour chaque année 1991-2020."""
    out = []
    today_year = dates[-1].year
    for y in YEARS:
        s, ok = 0.0, True
        for d in dates:
            yy = d.year - (today_year - y)
            dd = 28 if (d.month, d.day) == (2, 29) else d.day
            v = zone_value(raw, zp, 2, yy, d.month, dd) if yy in YEARS else None
            if v is None:
                ok = False
                break
            s += v
        if ok:
            out.append(round(s, 1))
    return out if len(out) >= MIN_YEARS else []


def build_zone_series(zones: list[dict], forecast: dict, normals: dict) -> dict:
    """Interface commune avec l'analyse : {zone_id: {time, i0, tx, tn, pr, et0, ntx, ntn, npr,
    sdtx, sdtn, clim_pr_obs30, clim_pr_fc14}} (normales à None si pas encore disponibles)."""
    times = forecast["time"]
    dates = [date.fromisoformat(t) for t in times]
    i0 = PAST_DAYS
    raw = {}
    for _, lat, lon, _ in all_points(zones):
        k = point_key(lat, lon)
        if k not in raw:
            raw[k] = load_raw(k)
    out = {}
    for z in zones:
        zp = _zone_points(z)
        keys, w = [k for k, _ in zp], [wt for _, wt in zp]
        agg = lambda var: [_r(_wmean([forecast["points"][k][var][i] for k in keys], w)) for i in range(len(times))]
        nz = normals.get(z["id"], {})
        pick = lambda name: [nz.get(name, [None] * 366)[doy(d)] for d in dates]
        sdx = [v for v in pick("sdtx") if v is not None]
        sdn = [v for v in pick("sdtn") if v is not None]
        out[z["id"]] = {
            "time": times, "i0": i0,
            "tx": agg(0), "tn": agg(1), "pr": agg(2), "et0": agg(3),
            "ntx": pick("ntx"), "ntn": pick("ntn"), "npr": pick("npr"),
            "sdtx": _r(mean(sdx), 2) if len(sdx) == len(dates) else None,
            "sdtn": _r(mean(sdn), 2) if len(sdn) == len(dates) else None,
            "clim_pr_obs30": _yearly_sums(raw, zp, dates[i0 - 30:i0]),
            "clim_pr_fc14": _yearly_sums(raw, zp, dates[i0:i0 + 14]),
        }
    return out
