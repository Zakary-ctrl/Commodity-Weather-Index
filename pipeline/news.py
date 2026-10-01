"""Actualités récentes par zone : titres et liens vers les articles d'origine.

Source principale : Google News (flux RSS de recherche, articles en anglais des 14 derniers jours).
Secours : GDELT (base ouverte d'actualités mondiales). Seuls le titre, la source, la date et le lien
sont conservés ; le lecteur est renvoyé vers le site de l'éditeur.
Sortie : data/news.json
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "news.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}
GNEWS = "https://news.google.com/rss/search"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
WEATHER = "(weather OR drought OR rain OR rains OR frost OR heat OR heatwave OR harvest OR crop OR planting)"
MAX_ITEMS = 6

# mot-clé de culture (français, dans zones.json) -> terme de recherche anglais
CROP_Q = [("Café", "coffee"), ("Cacao", "cocoa"), ("Canne", "sugarcane OR sugar"), ("Betterave", "sugar beet"),
          ("Maïs", "corn OR maize"), ("Soja", "soybean OR soy"), ("Blé", "wheat"), ("Riz", "rice"),
          ("Coton", "cotton"), ("palme", "palm oil"), ("Colza", "rapeseed"), ("Canola", "canola"),
          ("Tournesol", "sunflower"), ("Thé", "tea"), ("Oranges", "orange OR citrus")]


# lieux plus précis que le pays quand plusieurs zones partagent un même pays
LIEU = {
    "us_cornbelt": ['"Corn Belt"', "Midwest", "Iowa", "Illinois"], "us_plains": ["Kansas", "Oklahoma", '"Plains"'],
    "us_cotton": ["Texas", '"U.S."'], "ca_prairies": ["Saskatchewan", "Alberta", "Canada"],
    "br_conilon": ["Brazil", '"Espirito Santo"', "conilon", "robusta"], "br_matogrosso": ['"Mato Grosso"', "Brazil"],
    "br_citrus": ["Brazil", '"Sao Paulo"'], "cn_cotton": ["Xinjiang"], "cn_northeast": ["Heilongjiang", '"northeast China"'],
    "cn_ncp": ["Henan", "Shandong", '"North China"'], "cn_sugar": ["Guangxi"], "in_tea": ["Assam", "Darjeeling"],
    "in_cotton": ["Gujarat", "Maharashtra", "India"], "in_sugar": ["Maharashtra", '"Uttar Pradesh"', "India"],
    "borneo_palm": ["Sabah", "Sarawak", "Kalimantan"], "my_sum_palm": ["Malaysia", "Sumatra"],
    "id_robusta": ["Indonesia", "Sumatra"], "au_cane": ["Queensland"], "tr_cotton": ["Turkey"],
}


def _query(zone: dict, en: dict) -> str:
    crops = []
    for c in zone["cultures"]:
        for kw, q in CROP_Q:
            if kw.lower() in c.lower() and q not in crops:
                crops.append(q)
                break
    crops = crops[:3]
    if zone["id"] in LIEU:
        cq = " OR ".join(LIEU[zone["id"]])
    else:
        countries = [p.strip() for p in en.get(zone["pays"], zone["pays"]).split("/")]
        cq = " OR ".join(f'"{c}"' if " " in c else c for c in countries)
    kq = " OR ".join(crops)
    return f"({kq}) ({cq}) {WEATHER}"


def _clean_title(t: str, source: str) -> str:
    if source and t.endswith(" - " + source):
        t = t[: -len(source) - 3]
    return re.sub(r"\s+", " ", t).strip()


def _google(q: str) -> list[dict]:
    r = requests.get(GNEWS, params={"q": q + " when:14d", "hl": "en-US", "gl": "US", "ceid": "US:en"}, headers=UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        src = it.findtext("source") or ""
        try:
            d = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            d = None
        out.append({"titre": _clean_title(it.findtext("title") or "", src), "source": src, "date": d, "lien": it.findtext("link")})
    return out


def _gdelt(q: str) -> list[dict]:
    r = requests.get(GDELT, params={"query": q + " sourcelang:english", "mode": "artlist", "format": "json",
                                    "maxrecords": 20, "timespan": "14d", "sort": "datedesc"}, headers=UA, timeout=30)
    r.raise_for_status()
    arts = r.json().get("articles", [])
    return [{"titre": a.get("title", "").strip(), "source": a.get("domain", ""), "date": (a.get("seendate") or "")[:8]
             and f'{a["seendate"][:4]}-{a["seendate"][4:6]}-{a["seendate"][6:8]}', "lien": a.get("url")} for a in arts]


def update(zones: list[dict], log=print) -> dict:
    en_path = ROOT / "config" / "i18n_en.json"
    en = json.loads(en_path.read_text()) if en_path.exists() else {}
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    items, ok = dict(prev.get("zones", {})), 0
    for z in zones:
        q = _query(z, en)
        arts = []
        try:
            arts = _google(q)
        except Exception:  # noqa: BLE001
            try:
                time.sleep(6)
                arts = _gdelt(q)
            except Exception:  # noqa: BLE001
                arts = []
        seen, keep = set(), []
        for a in sorted(arts, key=lambda a: a["date"] or "", reverse=True):
            key = a["titre"].lower()[:60]
            if a["titre"] and a["lien"] and key not in seen:
                seen.add(key)
                keep.append(a)
            if len(keep) >= MAX_ITEMS:
                break
        if keep:
            items[z["id"]] = keep
            ok += 1
        time.sleep(1.5)
    out = {"maj": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "source": "Google News (recherche par zone, 14 derniers jours), GDELT en secours", "zones": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    log(f"Actualités : {ok}/{len(zones)} zones avec des articles")
    return out
