"""
Sembol evreni + metinden ticker cikarimi.

PULSE ile paylasim noktasi: evren dosyasi, PULSE'un
vendor_acceptance/full_universe_593.txt dosyasiyla AYNI formatta
(satir basina bir sembol). Istenirse dogrudan o dosya kopyalanabilir --
ama bu proje PULSE'a BAGIMLI DEGILDIR (bagimsiz process ilkesi).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "universe.txt"
DEFAULT_ALIASES_PATH = Path(__file__).resolve().parent.parent / "data" / "company_aliases.json"

# Turkce/finans metinlerinde ticker'a benzeyen ama ticker OLMAYAN yaygin
# buyuk harfli kisaltmalar -- yanlis pozitifleri onler.
STOPWORDS = {
    "BIST", "KAP", "SPK", "TCMB", "USD", "EUR", "TRY", "TL", "ABD", "AB",
    "GSYH", "TUFE", "UFE", "FED", "ECB", "IMF", "OECD", "KDV", "BSMV",
    "VIOP", "XU100", "XU030", "XBANK", "HTTP", "HTTPS", "WWW", "PDF",
    "AS", "VE", "ILE", "ICIN", "DA", "DE", "BU", "OL", "AB",
}


def load_universe(path: str | os.PathLike | None = None) -> set[str]:
    """Gecerli sembol kumesini dosyadan okur. Dosya yoksa BOS kume doner
    ve cagiran taraf bunu acikca ele alir (fail-closed: bos evrenle
    INFERRED eslesme YAPILMAZ, cunku her buyuk harfli kelime ticker
    sanilirdi)."""
    p = Path(path) if path else DEFAULT_UNIVERSE_PATH
    if not p.exists():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip().upper()
        if not s or s.startswith("#"):
            continue
        out.add(s)
    return out


_TOKEN_RE = re.compile(r"\b[A-Z0-9]{3,6}\b")


def extract_tickers(text: str, universe: set[str]) -> tuple[str, ...]:
    """Metinden ticker cikarir (INFERRED eslesme).

    Kurallar:
      - Evren BOSSA hicbir sey cikarilmaz (fail-closed).
      - Sadece evrende GERCEKTEN var olan semboller kabul edilir.
      - STOPWORDS elenir.
      - Turkce buyuk harfler (İ, Ş, Ğ...) ASCII karsiliklarina cevrilerek
        de denenir -- "İŞ BANKASI" gibi metinlerde yanlis eslesmeyi
        onlemek icin stopword kontrolu cevrimden SONRA yapilir.
    """
    if not universe or not text:
        return ()

    # Matcher v2: tokenleri metni komple upper() yaparak aramak YASAK.
    # Aksi halde kisi/sehir adlari ticker'a donusebilir:
    #   "Yiğit" -> YIGIT, "Uşak" -> USAK.
    # Dogrudan sembol eslesmesi icin token kaynak metinde zaten buyuk
    # harfli/ASCII ticker biciminde yazilmis olmali (ESCOM, THYAO vb.).
    found = []
    for tok in _TOKEN_RE.findall(text):
        norm = tok.upper()
        if norm in STOPWORDS:
            continue
        if norm in universe and norm not in found:
            found.append(norm)
    return tuple(found)


def is_valid_ticker(symbol: str, universe: set[str]) -> bool:
    return symbol.strip().upper() in universe


# ---------------------------------------------------------------------
# Sirket adi -> hisse kodu eslemesi
#
# Gerekce: haber metinleri cogu zaman sembol yazmaz. "Garanti Bankasi
# 3. ceyrek karini acikladi" cumlesinde GARAN gecmez -- sembol tabanli
# cikarim bu haberi KACIRIR. Alias tablosu bu boslugu kapatir.
#
# Yanlis pozitif riski gercek: cok kisa/genel bir alias ("is bankasi")
# alakasiz metinlerde eslesebilir. Bu yuzden tablo muhafazakar tutulur
# ve eslesme yine INFERRED olarak isaretlenir (EXACT DEGIL).
# ---------------------------------------------------------------------

_TR_UPPER = str.maketrans("ÇĞİÖŞÜÂÎ", "CGIOSUAI")
_TR_LOWER = str.maketrans("çğıöşüâî", "cgiosuai")


def _norm_text(text: str) -> str:
    """Turkce-guvenli normalizasyon (bkz. kap_subjects._norm -- ayni
    'İ'.lower() tuzagi burada da gecerli)."""
    t = (text or "").translate(_TR_UPPER).lower().translate(_TR_LOWER)
    return t.replace("\u0307", "")


def load_company_aliases(path: str | os.PathLike | None = None) -> dict[str, str]:
    """{normalize edilmis sirket adi: TICKER} sozlugu doner."""
    p = Path(path) if path else DEFAULT_ALIASES_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, str] = {}
    for name, ticker in raw.items():
        if name.startswith("_") or not isinstance(ticker, str):
            continue
        key = _norm_text(name).strip()
        if key:
            out[key] = ticker.strip().upper()
    return out


def extract_tickers_with_aliases(text: str, universe: set[str],
                                  aliases: dict[str, str] | None = None) -> tuple[str, ...]:
    """Once sembol kodlarini (ESCOM), sonra sirket adlarini (Garanti
    Bankasi -> GARAN) arar. Sonuc birlestirilir, sira korunur.

    Alias eslesmesi de evrene karsi dogrulanir -- tabloda olup evrende
    olmayan bir kod kabul edilmez."""
    found = list(extract_tickers(text, universe))
    # Evren bossa alias eslemesi de YAPILMAZ -- sembol cikarimiyla ayni
    # fail-closed ilkesi (evren bilinmeden hicbir kod dogrulanamaz).
    if not aliases or not universe:
        return tuple(found)

    hay = _norm_text(text)
    for name, ticker in aliases.items():
        if ticker in found:
            continue
        if ticker not in universe:
            continue
        # Alias substring degil, kelime/ifade sinirinda eslesir. Bu;
        # "thy" gibi kisa aliaslarin baska bir kelimenin icinde
        # yanlis eslesmesini engeller.
        pat = r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])"
        if re.search(pat, hay):
            found.append(ticker)
    return tuple(found)
