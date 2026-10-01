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
TOPIC_Q = "(price OR prices OR futures OR harvest OR crop OR output OR production OR exports OR imports OR weather OR drought OR rain OR frost)"
MAX_ITEMS = 6

# mot-clé de culture (français, dans zones.json) -> (requête, mots attendus dans le titre)
CROPS = [("Café", "coffee OR arabica OR robusta", ["coffee", "arabica", "robusta", "conilon"]),
         ("Cacao", "cocoa", ["cocoa", "cacao"]),
         ("Canne", "sugar OR sugarcane", ["sugar", "sugarcane", "cane", "ethanol"]),
         ("Betterave", "sugar beet", ["sugar", "beet"]),
         ("Maïs", "corn OR maize", ["corn", "maize"]),
         ("Soja", "soybean OR soybeans OR soy", ["soy", "soybean", "soybeans", "soymeal", "soyoil"]),
         ("Blé", "wheat", ["wheat", "grain", "grains"]),
         ("Riz", "rice", ["rice", "paddy"]),
         ("Coton", "cotton", ["cotton"]),
         ("palme", '"palm oil"', ["palm oil", "palm", "cpo"]),
         ("Colza", "rapeseed OR canola", ["rapeseed", "canola"]),
         ("Canola", "canola", ["canola", "rapeseed"]),
         ("Tournesol", "sunflower", ["sunflower", "sunoil"]),
         ("Thé", "tea", ["tea"]),
         ("Oranges", '"orange juice" OR citrus OR oranges', ["orange", "oranges", "citrus", "oj"])]

# mots qui font d'un titre une info de marché, de récolte, de commerce ou de météo agricole
TOPIC = ["price", "prices", "futures", "market", "markets", "harvest", "crop", "crops", "output", "production", "produce",
         "yield", "yields", "export", "exports", "import", "imports", "shipment", "shipments", "tonnes", "tons", "bags",
         "stocks", "supply", "supplies", "demand", "deficit", "surplus", "shortage", "glut", "weather", "drought", "dry",
         "dryness", "rain", "rains", "rainfall", "wet", "flood", "floods", "frost", "heat", "heatwave", "monsoon",
         "el nino", "el niño", "la nina", "la niña", "planting", "sowing", "acreage", "usda", "conab", "forecast",
         "estimate", "estimates", "tariff", "tariffs", "trade", "mills", "crush", "crushing", "grind", "grindings",
         "auction", "rally", "rallies", "surge", "surges", "jump", "jumps", "slump", "slumps", "falls", "fall", "rise",
         "rises", "gain", "gains", "drop", "drops", "record", "season", "farmers", "growers", "procurement"]
FARM = ["harvest", "harvests", "crop", "crops", "yield", "yields", "planting", "sowing", "farmers", "growers", "monsoon",
        "drought", "frost", "grain", "grains", "mills", "acreage"]
OTHER = ["garlic", "avocado", "avocados", "mango", "mangoes", "potato", "potatoes", "lentil", "lentils", "onion", "tomato",
         "banana", "bananas", "cattle", "beef", "pork", "hog", "hogs", "dairy", "milk", "poultry", "egg", "eggs", "fish",
         "shrimp", "salmon", "wine", "grape", "grapes", "apple", "apples", "cashew", "pepper", "rubber", "timber", "gold", "oil price", "crude"]
BLOCK = ["recipe", "recipes", "restaurant", "restaurants", "café", "cafe", "cafes", "coffee shop", "barista", "latte",
         "starbucks", "brew", "pairing", "pairings", "tourism", "festival", "valentine", "celebrat", "international coffee day",
         "international tea day", "health benefits", "manifesto", "election", "football", "lottery", "horoscope",
         "obituary", "concert", "fashion week", "skincare", "beauty"]
BAD_SOURCES = ["britannica", "slurrp", "caterer", "cobb courier", "bioengineer", "wikipedia", "pinterest", "youtube"]
GOOD_SOURCES = ["reuters", "bloomberg", "barchart", "s&p global", "spglobal", "argus", "fastmarkets", "dtn", "agweb",
                "successful farming", "farm progress", "brownfield", "world grain", "grain central", "ukragroconsult",
                "comunicaffe", "confectionery", "chinimandi", "datamar", "fibre2fashion", "nasdaq", "financial times",
                "wall street journal", "the business times", "business recorder", "the edge", "the star", "nikkei",
                "hellenic shipping", "agrimoney", "farmers weekly", "farmtario", "western producer", "rfd-tv", "agrolatam",
                "fresh plaza", "food navigator", "global agriculture", "the economic times", "business standard",
                "cocoa post", "modern ghana", "myjoyonline", "abc rural", "weekly times", "commodity"]

# lieux plus précis que le pays quand plusieurs zones partagent un même pays
LIEU = {
    "us_cornbelt": ['"Corn Belt"', "Midwest", "Iowa", "Illinois"], "us_plains": ["Kansas", "Oklahoma", '"Plains"'],
    "us_cotton": ["Texas", '"U.S."'], "ca_prairies": ["Saskatchewan", "Alberta", "Canada"],
    "br_conilon": ["Brazil", '"Espirito Santo"', "conilon"], "br_matogrosso": ['"Mato Grosso"', "Brazil"],
    "br_citrus": ["Brazil", '"Sao Paulo"', "Florida"], "cn_cotton": ["Xinjiang", "China"], "cn_northeast": ["Heilongjiang", '"northeast China"', "China"],
    "cn_ncp": ["Henan", "Shandong", '"North China"', "China"], "cn_sugar": ["Guangxi", "China"], "in_tea": ["Assam", "Darjeeling", "India"],
    "in_cotton": ["Gujarat", "Maharashtra", "India"], "in_sugar": ["Maharashtra", '"Uttar Pradesh"', "India"],
    "borneo_palm": ["Sabah", "Sarawak", "Kalimantan", "Malaysia", "Indonesia"], "my_sum_palm": ["Malaysia", "Sumatra", "Indonesia"],
    "id_robusta": ["Indonesia", "Sumatra", "Lampung"], "au_cane": ["Queensland", "Australia"], "tr_cotton": ["Turkey", "Türkiye"],
    "cam_coffee": ["Honduras", "Guatemala", "Nicaragua", '"Costa Rica"', '"Central America"'],
    "af_cocoa": ['"Ivory Coast"', '"Côte d\'Ivoire"', "Ghana"], "fertile_crescent": ["Syria", "Iraq"],
}
# adjectifs de nationalité acceptés dans les titres
DEMONYM = {"Brazil": ["brazilian"], "Ghana": ["ghanaian", "cocobod"], "Ivory Coast": ["ivorian"], "Côte d'Ivoire": ["ivorian"],
           "Vietnam": ["vietnamese"], "India": ["indian"], "China": ["chinese"], "Indonesia": ["indonesian"],
           "Malaysia": ["malaysian", "mpob"], "Russia": ["russian", "black sea"], "Ukraine": ["ukrainian", "black sea"],
           "Australia": ["australian"], "Argentina": ["argentine", "argentinian", "rosario"], "United States": ["u.s.", "us", "american", "usda"],
           "Canada": ["canadian"], "France": ["french", "eu", "europe", "euronext", "matif"], "Germany": ["german", "eu", "europe"],
           "Poland": ["polish", "eu", "europe"], "Romania": ["romanian", "black sea", "eu"], "Bulgaria": ["bulgarian", "black sea"],
           "Thailand": ["thai"], "Egypt": ["egyptian"], "Morocco": ["moroccan"], "Algeria": ["algerian"], "Tunisia": ["tunisian"],
           "Turkey": ["turkish", "türkiye"], "Iran": ["iranian"], "Kenya": ["kenyan", "mombasa"], "Ethiopia": ["ethiopian"],
           "Uganda": ["ugandan"], "Colombia": ["colombian"], "Mexico": ["mexican"], "Ecuador": ["ecuadorian"],
           "Nigeria": ["nigerian"], "Cameroon": ["cameroonian"], "South Africa": ["south african", "safex"],
           "Kazakhstan": ["kazakh"], "Syria": ["syrian"], "Iraq": ["iraqi"]}


def _crops(zone):
    out = []
    for c in zone["cultures"]:
        for kw, q, words in CROPS:
            if kw.lower() in c.lower() and (q, words) not in out:
                out.append((q, words))
                break
    return out[:3]


def _places(zone, en):
    if zone["id"] in LIEU:
        base = [p.strip('"') for p in LIEU[zone["id"]]]
    else:
        base = [p.strip() for p in en.get(zone["pays"], zone["pays"]).split("/")]
    words = [b.lower() for b in base]
    for b in base:
        words += DEMONYM.get(b, [])
    return base, words


def _queries(zone: dict, en: dict) -> list[str]:
    crops = _crops(zone)
    places, _ = _places(zone, en)
    kq = " OR ".join(q for q, _ in crops)
    pq = " OR ".join(f'"{p}"' if " " in p and not p.startswith('"') else p for p in places)
    main = crops[0][0] if crops else kq
    return [f"({kq}) ({pq}) {TOPIC_Q}", f"({main}) (prices OR futures OR harvest OR exports OR crop)"]


def _has(words, text):
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) for w in words)


def _score(a: dict, crop_words, place_words) -> float | None:
    t, src = a["titre"].lower(), (a["source"] or "").lower()
    if not t or sum(c.isascii() for c in t) < 0.9 * len(t):
        return None  # titres hors anglais
    if src == "t.co" or any(b in src for b in BAD_SOURCES) or any(b in t for b in BLOCK):
        return None
    crop, place = _has(crop_words, t), _has(place_words, t)
    topics = sum(1 for w in TOPIC if _has([w], t))
    if crop and topics == 0:
        return None  # la culture est citée, mais ni prix, ni récolte, ni commerce, ni météo
    if not crop and (not (place and _has(FARM, t)) or _has(OTHER, t)):
        return None  # sans la culture dans le titre : seulement une info agricole de la région
    sc = min(topics, 3) + (3 if place else 0) + (2 if crop else 0) + (2 if any(g in src for g in GOOD_SOURCES) else 0)
    if a.get("date"):
        try:
            age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(a["date"]).date()).days
            sc += max(0, 2 - age / 4)
        except ValueError:
            pass
    return sc


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
        crop_words = [w for _, ws in _crops(z) for w in ws]
        _, place_words = _places(z, en)
        arts = []
        for q in _queries(z, en):
            try:
                arts += _google(q)
            except Exception:  # noqa: BLE001
                try:
                    time.sleep(6)
                    arts += _gdelt(q)
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(1.5)
        scored = []
        for a in arts:
            sc = _score(a, crop_words, place_words) if a.get("titre") and a.get("lien") else None
            if sc is not None:
                scored.append((sc, a))
        seen, keep = set(), []
        for sc, a in sorted(scored, key=lambda x: (x[0], x[1]["date"] or ""), reverse=True):
            key = re.sub(r"[^a-z]", "", a["titre"].lower())[:50]
            if key in seen:
                continue
            seen.add(key)
            keep.append(a)
            if len(keep) >= MAX_ITEMS:
                break
        keep.sort(key=lambda a: a["date"] or "", reverse=True)
        items[z["id"]] = keep
        ok += bool(keep)
    out = {"maj": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "source": "Google News (recherche par zone et par culture, 14 derniers jours, titres filtrés), GDELT en secours", "zones": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    log(f"Actualités : {ok}/{len(zones)} zones avec des articles")
    return out
