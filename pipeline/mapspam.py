"""Poids de production réels des points, à partir de MapSPAM 2020 (IFPRI).

Exécuté une seule fois, automatiquement, par GitHub Actions (qui a accès à internet) :
télécharge la carte mondiale de production MapSPAM 2020 v2.2 (grille ~10 km, 46 cultures),
mesure pour chaque point la production de ses cultures dans un rayon d'environ 80 km,
et enregistre le résultat dans data/mapspam_weights.json.

Pour une zone à plusieurs cultures (ex. maïs + soja), le poids d'un point est la moyenne de
ses parts dans chaque culture de la zone : on ne mélange pas des tonnes de canne et de soja.
Source : IFPRI (2026), Global Spatially-Disaggregated Crop Production Statistics Data for 2020
Version 2.0 Release 2, https://doi.org/10.7910/DVN/SWPENT
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "mapspam_weights.json"
URL = ("https://www.dropbox.com/scl/fi/asxrhdtpvu2kbymii5a6z/spam2020V2r2_global_production.csv.zip"
       "?rlkey=lhoh7dpeskozqhuh7lli20udu&dl=1")
SOURCE = "MapSPAM 2020 v2.2 (IFPRI), production par culture sur grille de ~10 km"
HALF_BOX = 0.75  # demi-côté du carré autour de chaque point, en degrés (~80 km)
MIN_SHARE = 0.03  # un point garde toujours un poids minimal

# mots-clés des cultures (zones.json) -> codes MapSPAM candidats, par ordre de préférence
CROPS = [
    ("Robusta", ["RCOF", "COFF"]), ("Conilon", ["RCOF", "COFF"]), ("Arabica", ["ACOF", "COFF"]),
    ("Cacao", ["COCO"]), ("Maïs", ["MAIZ"]), ("Soja", ["SOYB"]), ("Blé", ["WHEA"]), ("Riz", ["RICE"]),
    ("Canne", ["SUGC"]), ("Betterave", ["SUGB"]), ("Coton", ["COTT"]), ("palme", ["OILP"]),
    ("Colza", ["RAPE"]), ("Canola", ["RAPE"]), ("Tournesol", ["SUNF"]), ("Thé", ["TEAS"]),
    ("Oranges", ["CITR", "ORAN", "TROF"]),
]


def _codes_for(cultures: list[str], available: set[str]) -> list[str]:
    out = []
    for c in cultures:
        for kw, cands in CROPS:
            if kw.lower() in c.lower():
                code = next((x for x in cands if x in available), None)
                if code and code not in out:
                    out.append(code)
                break
    return out


def _download() -> bytes:
    last = ""
    for attempt in range(3):
        try:
            r = requests.get(URL, timeout=600, allow_redirects=True)
            if r.status_code == 200 and r.content[:2] == b"PK":
                return r.content
            last = f"HTTP {r.status_code}, {len(r.content)} octets"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(30)
    raise RuntimeError("téléchargement MapSPAM impossible : " + last)


def _pick_csv(zf: zipfile.ZipFile) -> str:
    csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    # le fichier "toutes technologies" (_TA / _A) en priorité, sinon le plus gros
    for tag in ("_ta.csv", "_a.csv"):
        hit = [n for n in csvs if n.lower().endswith(tag)]
        if hit:
            return hit[0]
    return max(csvs, key=lambda n: zf.getinfo(n).file_size)


def compute(zones: list[dict], log=print) -> dict:
    import csv

    log("MapSPAM : téléchargement...")
    zf = zipfile.ZipFile(io.BytesIO(_download()))
    name = _pick_csv(zf)
    log(f"MapSPAM : lecture de {name}")
    reader = csv.reader(io.TextIOWrapper(zf.open(name), encoding="utf-8", errors="replace"))
    header = next(reader)
    low = {c.strip().lower(): i for i, c in enumerate(header)}
    xi = low.get("x", low.get("lon", low.get("longitude")))
    yi = low.get("y", low.get("lat", low.get("latitude")))
    ti = low.get("tech_type")  # certaines versions mettent toutes les technologies dans un seul fichier
    if xi is None or yi is None:
        raise RuntimeError(f"colonnes de coordonnées introuvables : {header[:15]}")
    crop_idx = {}
    for i, c in enumerate(header):
        base = c.strip().upper()
        if base.endswith("_A"):
            base = base[:-2]
        if len(base) == 4 and base.isalpha() and base not in crop_idx:
            crop_idx[base] = i
    available = set(crop_idx)
    needed = sorted({code for z in zones for code in _codes_for(z["cultures"], available)})
    log(f"MapSPAM : cultures utilisées {needed}")

    pts = [(z["id"], i, p[0], p[1]) for z in zones for i, p in enumerate(z["points"])]
    sums = {(zid, i): {c: 0.0 for c in needed} for zid, i, _, _ in pts}
    num = lambda v: float(v) if v not in ("", "NA", "nan") else 0.0
    n_rows = 0
    for row in reader:
        if ti is not None and row[ti].strip().upper() not in ("A", "TA", "ALL"):
            continue
        try:
            x, y = float(row[xi]), float(row[yi])
        except (ValueError, IndexError):
            continue
        n_rows += 1
        for zid, i, lat, lon in pts:
            if abs(y - lat) <= HALF_BOX and abs(x - lon) <= HALF_BOX:
                acc = sums[(zid, i)]
                for c in needed:
                    acc[c] += num(row[crop_idx[c]])
    log(f"MapSPAM : {n_rows} cellules lues")

    weights, detail = {}, {}
    for z in zones:
        codes = _codes_for(z["cultures"], available)
        n = len(z["points"])
        shares = []
        for c in codes:
            tot = sum(sums[(z["id"], i)][c] for i in range(n))
            if tot > 0:
                shares.append([sums[(z["id"], i)][c] / tot for i in range(n)])
        if not shares:
            log(f"  {z['id']:14} pas de production trouvée, poids estimés conservés")
            continue
        w = [max(MIN_SHARE, sum(s[i] for s in shares) / len(shares)) for i in range(n)]
        tot = sum(w)
        weights[z["id"]] = [round(10 * x / tot, 2) for x in w]
        detail[z["id"]] = {"cultures": codes,
                           "production_t": [{c: round(sums[(z["id"], i)][c]) for c in codes} for i in range(n)]}
        log(f"  {z['id']:14} {codes} -> {weights[z['id']]}")
    return {"source": SOURCE, "calcule_le": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "rayon_deg": HALF_BOX, "poids": weights, "detail": detail}


def load_weights() -> dict | None:
    return json.loads(OUT.read_text()) if OUT.exists() else None


def apply_weights(zones: list[dict]) -> str | None:
    """Remplace les poids estimés par les poids MapSPAM quand ils existent. Renvoie la source."""
    w = load_weights()
    if not w or "poids" not in w:
        return None
    for z in zones:
        pw = w["poids"].get(z["id"])
        if pw and len(pw) == len(z["points"]):
            for p, x in zip(z["points"], pw):
                p[2] = x
    return w["source"]


def ensure(zones: list[dict], log=print) -> bool:
    """Calcule les poids une seule fois. En cas d'échec, un nouvel essai au plus une fois par jour."""
    if OUT.exists():
        prev = json.loads(OUT.read_text())
        if "poids" in prev:
            return False
        last = datetime.fromisoformat(prev.get("essai", "2000-01-01T00:00+00:00"))
        if (datetime.now(timezone.utc) - last).total_seconds() < 86400:
            return False
    try:
        res = compute(zones, log)
    except Exception as e:  # jamais bloquant pour le reste du calcul
        log(f"MapSPAM indisponible ({str(e)[:200]}), poids estimés conservés.")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"essai": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                                   "erreur": str(e)[:500]}))
        return False
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return True
