"""
Depolama katmani -- PULSE'un raw/manifest/state ayrimiyla ayni desen.

  data/raw/      : ham kaynak yanitlari, ASLA uzerine yazilmaz (provenance)
  data/store/news.jsonl : contract'a uygun kayitlar (append-only)
  data/store/collector_state.json : kaynak bazli son toplama durumu (atomik)

YAZMA SADECE COLLECTOR TARAFINDAN YAPILIR. API/UI bu modulu yalnizca
OKUMAK icin kullanir (read_* fonksiyonlari). Bu, PULSE'un
"collector=writer, PULSE=read-only consumer" ilkesinin birebir karsiligi.

Idempotency: ayni haber tekrar toplandiginda item_id ayni uretilir ve
ikinci kez YAZILMAZ.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from haber.contract import NewsItem

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
STORE_DIR = BASE_DIR / "data" / "store"
NEWS_PATH = STORE_DIR / "news.jsonl"
STATE_PATH = STORE_DIR / "collector_state.json"


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", part)[:60]


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def save_raw(source_id: str, raw_text: str, run_id: str, failed: bool = False) -> str:
    """Ham yaniti diske yazar ve yolunu doner. ASLA uzerine yazmaz --
    her cagri benzersiz dosya adi uretir (zaman damgasi + run_id).

    failed=True ise dosya adina 'FAILED' eklenir. Basarisiz yanitlar da
    KORUNUR (PULSE dersi: raw once korunur, validation sonra) -- ama
    klasorde goz ile ayirt edilebilmeleri gerekir."""
    ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    marker = "FAILED_" if failed else ""
    fname = f"{marker}{_safe(source_id)}_{ts}_{_safe(run_id)}.raw"
    path = RAW_DIR / fname
    counter = 0
    while path.exists():  # teorik carpisma -- yine de uzerine YAZMA
        counter += 1
        path = RAW_DIR / f"{marker}{_safe(source_id)}_{ts}_{_safe(run_id)}_{counter}.raw"
    path.write_text(raw_text, encoding="utf-8")
    return str(path.relative_to(BASE_DIR))


def read_existing_ids() -> set[str]:
    """Deposundaki tum item_id'ler -- idempotent yazma icin."""
    if not NEWS_PATH.exists():
        return set()
    ids = set()
    with NEWS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["item_id"])
            except Exception:
                continue  # bozuk satir okumayi durdurmaz
    return ids


def append_items(items: Iterable[NewsItem], known_ids: Optional[set[str]] = None) -> int:
    """Yeni kayitlari ekler (append-only). Zaten var olanlar ATLANIR.
    Kac YENI kayit yazildigini doner."""
    ensure_dirs()
    if known_ids is None:
        known_ids = read_existing_ids()

    written = 0
    with NEWS_PATH.open("a", encoding="utf-8") as f:
        for item in items:
            if item.item_id in known_ids:
                continue
            f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            known_ids.add(item.item_id)
            written += 1
    return written


def read_all() -> list[NewsItem]:
    """Tum kayitlari okur. SADECE OKUMA -- ag yok, yazma yok."""
    if not NEWS_PATH.exists():
        return []
    out = []
    with NEWS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(NewsItem.from_dict(json.loads(line)))
            except Exception:
                continue
    return out


def save_state(state: dict) -> None:
    """Atomik yazma -- yarim dosya riski yok (PULSE state deseni)."""
    ensure_dirs()
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def read_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
