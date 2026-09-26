"""
Izleme listeleri (watchlist).

MIMARI NOT -- neden bu "veri" degil "konfigurasyon":
  Toplanan haberler (news.jsonl) SADECE collector tarafindan yazilir;
  API oraya ASLA yazmaz. Izleme listesi ise kullanicinin kendi tercihi --
  ayri bir dosyada (watchlists.json) tutulur ve API bu TEK dosyaya
  yazabilir. Boylece "collector veri deposunun tek sahibidir" garantisi
  bozulmaz. Bir test bunu ayrica dogrular.

Dosya elle de duzenlenebilir:
  {"BOLT": ["ESCOM","ARDYZ"], "AEGIS": ["GARAN","AKBNK"]}
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WATCHLISTS_PATH = BASE_DIR / "data" / "watchlists.json"

MAX_NAME_LEN = 24
MAX_TICKERS_PER_LIST = 200
MAX_LISTS = 20

_NAME_RE = re.compile(r"^[A-Za-z0-9ÇĞİÖŞÜçğıöşü _-]{1,24}$")
_TICKER_RE = re.compile(r"^[A-Z0-9]{3,6}$")


class WatchlistError(ValueError):
    """Gecersiz liste adi/icerigi -- fail-closed, sessizce duzeltilmez."""


def validate_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise WatchlistError("Liste adi bos olamaz")
    if len(n) > MAX_NAME_LEN:
        raise WatchlistError(f"Liste adi en fazla {MAX_NAME_LEN} karakter olabilir")
    if not _NAME_RE.match(n):
        raise WatchlistError("Liste adinda gecersiz karakter var")
    return n


def normalize_tickers(tickers, universe: set[str] | None = None) -> list[str]:
    """Sembolleri buyuk harfe cevirir, tekrarlari atar, sirayi korur.

    universe verilirse, evrende OLMAYAN semboller REDDEDILIR -- yazim
    hatasiyla hicbir zaman eslesmeyecek bir liste olusturmayi onler.
    Evren bos/None ise bu kontrol atlanir (evren dosyasi yoksa arac
    yine de kullanilabilsin diye)."""
    if not isinstance(tickers, (list, tuple)):
        raise WatchlistError("Sembol listesi dizi olmali")
    if len(tickers) > MAX_TICKERS_PER_LIST:
        raise WatchlistError(f"Bir listede en fazla {MAX_TICKERS_PER_LIST} sembol olabilir")

    out: list[str] = []
    unknown: list[str] = []
    for t in tickers:
        s = str(t).strip().upper()
        if not s:
            continue
        if not _TICKER_RE.match(s):
            raise WatchlistError(f"Gecersiz sembol formati: {t!r}")
        if universe and s not in universe:
            unknown.append(s)
            continue
        if s not in out:
            out.append(s)

    if unknown:
        raise WatchlistError(
            "Sembol evreninde bulunmayan kod(lar): " + ", ".join(sorted(set(unknown)))
        )
    return out


def load_all() -> dict[str, list[str]]:
    if not WATCHLISTS_PATH.exists():
        return {}
    try:
        data = json.loads(WATCHLISTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, tickers in data.items():
        if not isinstance(tickers, list):
            continue
        clean = [str(t).strip().upper() for t in tickers if str(t).strip()]
        out[str(name)] = [t for i, t in enumerate(clean) if t not in clean[:i]]
    return out


def save_all(lists: dict[str, list[str]]) -> None:
    """Atomik yazma -- yarim dosya riski yok."""
    WATCHLISTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WATCHLISTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(lists, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, WATCHLISTS_PATH)


def upsert(name: str, tickers, universe: set[str] | None = None) -> dict[str, list[str]]:
    """Liste olusturur veya gunceller."""
    name = validate_name(name)
    clean = normalize_tickers(tickers, universe)
    lists = load_all()
    if name not in lists and len(lists) >= MAX_LISTS:
        raise WatchlistError(f"En fazla {MAX_LISTS} liste olabilir")
    lists[name] = clean
    save_all(lists)
    return lists


def delete(name: str) -> dict[str, list[str]]:
    lists = load_all()
    lists.pop(name, None)
    save_all(lists)
    return lists


def get_tickers(name: str) -> list[str]:
    return load_all().get(name, [])
