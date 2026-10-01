"""Cours des contrats à terme (clôtures quotidiennes, Yahoo Finance, contrat le plus proche).

Pour les marchés sans cotation gratuite (Euronext, Londres, Bursa Malaysia...), on affiche
la référence liquide la plus proche, signalée comme telle sur le site.
Sortie : data/prices.json
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prices.json"
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}

# ticker Yahoo -> nom, unité
TICKERS = {
    "KC=F": ("ICE Coffee C (KC)", "¢/lb"),
    "CC=F": ("ICE Cocoa New York (CC)", "$/t"),
    "SB=F": ("ICE Sugar No.11 (SB)", "¢/lb"),
    "CT=F": ("ICE Cotton No.2 (CT)", "¢/lb"),
    "OJ=F": ("ICE FCOJ (OJ)", "¢/lb"),
    "ZC=F": ("CBOT Corn (ZC)", "¢/bu"),
    "ZS=F": ("CBOT Soybeans (ZS)", "¢/bu"),
    "ZW=F": ("CBOT Wheat (ZW)", "¢/bu"),
    "KE=F": ("KC HRW Wheat (KE)", "¢/bu"),
    "ZL=F": ("CBOT Soybean Oil (ZL)", "¢/lb"),
}
# contrat cité dans zones.json -> (ticker, cotation directe ?)
CONTRACTS = {
    "ICE Coffee C (KC)": ("KC=F", True),
    "ICE Robusta Londres (RC)": ("KC=F", False),
    "ICE Cocoa New York (CC)": ("CC=F", True),
    "ICE Cocoa Londres (C)": ("CC=F", False),
    "ICE Sugar No.11 (SB)": ("SB=F", True),
    "ICE Sugar No.16 (US)": ("SB=F", False),
    "Sucre blanc Londres (No.5)": ("SB=F", False),
    "ICE Cotton No.2 (CT)": ("CT=F", True),
    "ICE FCOJ (OJ)": ("OJ=F", True),
    "CBOT Corn (ZC)": ("ZC=F", True),
    "CBOT Soybeans (ZS)": ("ZS=F", True),
    "CBOT Wheat (ZW)": ("ZW=F", True),
    "KC HRW Wheat (KE)": ("KE=F", True),
    "CBOT Soybean Oil (ZL)": ("ZL=F", True),
    "Euronext Blé meunier (EBM)": ("ZW=F", False),
    "Euronext Maïs (EMA)": ("ZC=F", False),
    "Euronext Colza (ECO)": ("ZL=F", False),
    "ICE Canola (RS)": ("ZL=F", False),
    "Bursa Malaysia (FCPO)": ("ZL=F", False),
    "Blé HRS (MIAX)": ("KE=F", False),
    "ASX Wheat": ("ZW=F", False),
    "Prix FOB mer Noire": ("ZW=F", False),
    "SAFEX (JSE) maïs": ("ZC=F", False),
}


def _fetch(ticker: str) -> dict | None:
    for attempt in range(3):
        try:
            r = requests.get(URL.format(ticker), params={"range": "1y", "interval": "1d"}, headers=UA, timeout=30)
            if r.status_code == 200:
                res = r.json()["chart"]["result"][0]
                ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
                rows = [(datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), round(c, 2))
                        for t, c in zip(ts, cl) if c is not None]
                return {"nom_court": res["meta"].get("shortName"), "dates": [d for d, _ in rows], "close": [c for _, c in rows]}
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
            pass
        time.sleep(5 * (attempt + 1))
    return None


def update(log=print) -> dict:
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    series = dict(prev.get("series", {}))
    ok = 0
    for t, (name, unit) in TICKERS.items():
        s = _fetch(t)
        if s:
            series[t] = {"nom": name, "unite": unit, **s}
            ok += 1
        time.sleep(1)
    out = {"maj": datetime.now(timezone.utc).isoformat(timespec="minutes"), "source": "Yahoo Finance (contrat le plus proche, clôture)",
           "contrats": {c: {"ticker": t, "direct": d} for c, (t, d) in CONTRACTS.items()}, "series": series}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    log(f"Prix : {ok}/{len(TICKERS)} contrats mis à jour")
    return out
