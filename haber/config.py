"""
Kaynak konfigurasyonu.

Yeni kaynak eklemek = buraya bir satir eklemek. Collector, store, API ve
UI DEGISMEZ (vendor-agnostic adaptor ilkesi).

sources.json varsa ondan okunur; yoksa asagidaki varsayilanlar kullanilir.
Boylece kaynak listesi kod degistirmeden duzenlenebilir.
"""
from __future__ import annotations

import json
from pathlib import Path

from haber.sources.base import NewsSource
from haber.sources.kap import KapNewsSource
from haber.sources.rss import RssNewsSource

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCES_CONFIG_PATH = BASE_DIR / "data" / "sources.json"

# Varsayilan RSS kaynaklari.
# NOT: Bu adresler yayincilar tarafindan degistirilebilir. Bir kaynak
# surekli hata veriyorsa once adresini dogrula (UI'daki saglik panelinde
# gorunur), sonra data/sources.json ile duzelt.
DEFAULT_RSS_SOURCES = [
    # --- DOGRULANMIS CALISANLAR (gercek calistirmada 200 + gecerli akis) ---
    ("BLOOMBERGHT", "https://www.bloomberght.com/rss"),
    ("DUNYA", "https://www.dunya.com/rss?dunya"),

    # --- ADAY (denenmedi -- calismazsa saglik panelinde gorunur) ---
    # Bigpara ve Mynet'in eski adresleri 404 verdi; asagidakiler
    # denenebilir. Calismayani data/sources.json'dan kapat.
    ("INVESTING_TR", "https://tr.investing.com/rss/news.rss"),
    ("PARATIC", "https://www.paratic.com/feed/"),
]

DEFAULT_KAP_ENABLED = True


def build_sources() -> list[NewsSource]:
    """Aktif kaynak adaptorlerini insa eder."""
    if SOURCES_CONFIG_PATH.exists():
        try:
            cfg = json.loads(SOURCES_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    else:
        cfg = {}

    sources: list[NewsSource] = []

    kap_cfg = cfg.get("kap", {})
    if kap_cfg.get("enabled", DEFAULT_KAP_ENABLED):
        endpoint = kap_cfg.get("endpoint")
        sources.append(KapNewsSource(endpoint=endpoint) if endpoint else KapNewsSource())

    rss_list = cfg.get("rss")
    if rss_list is None:
        rss_list = [{"source_id": sid, "url": url} for sid, url in DEFAULT_RSS_SOURCES]

    for entry in rss_list:
        if not entry.get("enabled", True):
            continue
        sources.append(RssNewsSource(source_id=entry["source_id"], feed_url=entry["url"]))

    return sources


def write_default_config() -> Path:
    """Duzenlenebilir bir sources.json olusturur (yoksa)."""
    if SOURCES_CONFIG_PATH.exists():
        return SOURCES_CONFIG_PATH
    SOURCES_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = {
        "_aciklama": "Kaynak listesi. enabled=false ile bir kaynagi kapatabilirsin.",
        "kap": {"enabled": True, "endpoint": None},
        "rss": [{"source_id": sid, "url": url, "enabled": True}
                for sid, url in DEFAULT_RSS_SOURCES],
    }
    SOURCES_CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return SOURCES_CONFIG_PATH
