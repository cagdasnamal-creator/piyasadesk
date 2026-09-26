"""
RETENTION_POLICY_V1 -- veri saklama penceresi.

Amac: bu arac gunluk/anlik haber takibi icin kullaniliyor; tarihsel
arsiv tutmuyor. Belirlenen pencereden eski veriler silinir.

TUTARLILIK KURALI (onemli):
    raw dosyalari ve haber kayitlari AYNI pencereyle budanir.
    Aksi halde bir haber kaydinin raw_ref alani silinmis bir dosyayi
    isaret ederdi -- provenance zinciri sessizce kirilirdi. Ikisini
    birlikte budamak, "her kaydin raw'i ya vardir ya kayit da yoktur"
    garantisini korur.

HANGI ZAMAN DAMGASI:
    Budama `collected_at` (BIZIM topladigimiz an) uzerinden yapilir,
    `published_at` uzerinden DEGIL. Sebep: published_at kaynak
    beyanidir, None olabilir veya bir yayinci eski bir haberi yeniden
    yayimlayabilir. collected_at her zaman vardir ve bizimdir.

ILERIDE PULSE ENTEGRASYONU:
    PULSE haber gecmisini backtest'te kullanmak isterse bu pencere
    yeniden degerlendirilmeli -- 7 gunluk pencere ile tarihsel analiz
    yapilamaz. O gun geldiginde ayrica konusulacak (bkz.
    PULSE_INTEGRATION_CONTRACT.md).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from haber import store

DEFAULT_RETENTION_DAYS = 7


def _parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def prune_raw(days: int = DEFAULT_RETENTION_DAYS, now: datetime | None = None) -> dict:
    """Pencereden eski ham yanit dosyalarini siler (dosya mtime'ina gore)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    raw_dir = Path(store.RAW_DIR)
    if not raw_dir.exists():
        return {"deleted": 0, "kept": 0, "freed_bytes": 0}

    deleted = kept = freed = 0
    for p in raw_dir.glob("*.raw"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except FileNotFoundError:
            continue
        if mtime < cutoff:
            try:
                size = p.stat().st_size
                p.unlink()
                deleted += 1
                freed += size
            except OSError:
                kept += 1
        else:
            kept += 1
    return {"deleted": deleted, "kept": kept, "freed_bytes": freed}


def prune_news(days: int = DEFAULT_RETENTION_DAYS, now: datetime | None = None) -> dict:
    """Pencereden eski haber kayitlarini siler.

    news.jsonl normalde append-only'dir; bu, bilincli bir bakim
    islemidir ve ATOMIK yapilir (tmp + replace) -- yarida kesilirse
    dosya bozulmaz.

    Zaman damgasi okunamayan bir kayit KORUNUR (fail-safe: silmek geri
    alinamaz, saklamak zararsizdir)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    path = Path(store.NEWS_PATH)
    if not path.exists():
        return {"deleted": 0, "kept": 0}

    kept_lines: list[str] = []
    deleted = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except Exception:
                kept_lines.append(s)   # bozuk satiri silme -- incelenebilsin
                continue
            ts = _parse_iso(rec.get("collected_at"))
            if ts is None or ts >= cutoff:
                kept_lines.append(s)
            else:
                deleted += 1

    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")
    os.replace(tmp, path)
    return {"deleted": deleted, "kept": len(kept_lines)}


def prune_all(days: int = DEFAULT_RETENTION_DAYS, now: datetime | None = None) -> dict:
    """Haber kayitlarini ve ham dosyalari AYNI pencereyle budar."""
    news = prune_news(days, now)
    raw = prune_raw(days, now)
    return {"retention_days": days, "news": news, "raw": raw}
