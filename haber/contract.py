"""
NEWS_CONTRACT_V1 -- Hisse Haber Merkezi'nin versiyonlu veri sozlesmesi.

PULSE mimarisiyle ayni ilkeler:
  - Versiyonlu, acik bir contract (sema sessizce degismez -- degisirse V2 olur)
  - Fail-closed: eksik/bozuk kayit SESSIZCE kabul edilmez
  - Provenance: her kaydin hangi kaynaktan, ne zaman, hangi ham yanittan
    geldigi izlenebilir
  - Freshness != completeness (bkz. health.py)

KRITIK SINIR -- NEWS != SIGNAL:
  Bu contract SADECE "su sembol hakkinda su haber yayinlandi" olgusunu
  tasir. Hicbir alan al/sat yonu, skor, tavsiye veya beklenen etki
  ICERMEZ. PULSE ileride bunu tuketirse, haber bir PulseSignal'in
  *metadata/reason_code* girdisi olabilir -- ASLA sinyalin kendisi
  olamaz. (PULSE'un "SIGNAL != ORDER" ayrimiyla ayni ruh.)

TELIF SINIRI:
  Tam makale metni SAKLANMAZ. Sadece baslik + kaynagin kendi verdigi
  kisa ozet + link tutulur. Tam metin icin kullanici kaynaga gider.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

CONTRACT_VERSION = "NEWS_CONTRACT_V1"

# Ozet icin ust sinir -- telif guvenligi. Kaynak daha uzun ozet verse bile
# burada kesilir.
MAX_SUMMARY_CHARS = 500

# --- Kaynak turu taksonomisi ---
SOURCE_KIND_REGULATORY = "REGULATORY"   # KAP -- resmi/yasal bildirim
SOURCE_KIND_MEDIA = "MEDIA"             # haber sitesi RSS
SOURCE_KIND_SOCIAL = "SOCIAL"           # (yuva -- henuz uygulanmadi)

VALID_SOURCE_KINDS = {SOURCE_KIND_REGULATORY, SOURCE_KIND_MEDIA, SOURCE_KIND_SOCIAL}

# --- Ticker eslesme guveni ---
# Bir haberin hangi sembole ait oldugu HER ZAMAN ayni kesinlikte bilinmez.
# KAP bildirimi sembolu YAPISAL olarak verir (EXACT). Bir haber sitesi
# metninde "ESCOM" gecmesi ise CIKARIM'dir (INFERRED). Bu ayrim UI'da
# gosterilir ve PULSE tarafinda filtrelenebilir olmali.
MATCH_EXACT = "EXACT"        # kaynak sembolu yapisal alanda verdi
MATCH_INFERRED = "INFERRED"  # metinden cikarildi

VALID_MATCH_CONFIDENCE = {MATCH_EXACT, MATCH_INFERRED}


@dataclass(frozen=True)
class NewsItem:
    """Tek bir haber/bildirim kaydi. IMMUTABLE -- bir kez yazildiktan
    sonra degistirilmez (PULSE'un raw-preservation ilkesiyle ayni)."""

    item_id: str              # deterministik kimlik (asagidaki make_item_id)
    contract_version: str
    source_id: str            # orn. "KAP", "BIGPARA_RSS"
    source_kind: str          # REGULATORY / MEDIA / SOCIAL
    tickers: tuple[str, ...]  # iliskili semboller (bos olabilir -- genel piyasa haberi)
    match_confidence: str     # EXACT / INFERRED
    title: str
    summary: str              # KISA ozet -- tam metin DEGIL
    url: str
    published_at: Optional[str]   # ISO8601 UTC; kaynak vermezse None
    collected_at: str             # ISO8601 UTC -- bizim topladigimiz an
    raw_ref: Optional[str] = None # ham yanit dosyasina referans (provenance)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "NewsItem":
        d = dict(d)
        d["tickers"] = tuple(d.get("tickers") or ())
        d.setdefault("raw_ref", None)
        d.setdefault("extra", {})
        return NewsItem(**d)


class ContractViolation(ValueError):
    """Kayit NEWS_CONTRACT_V1'i ihlal ediyor -- FAIL-CLOSED, sessizce
    kabul edilmez."""


def normalize_url(url: str) -> str:
    """Deduplication icin URL normalizasyonu: sema/host kucuk harf,
    izleme parametreleri (utm_*, fbclid vb.) atilir, sondaki / kaldirilir.
    Ayni haberin farkli linklerle iki kez girmesini engeller."""
    if not url:
        return ""
    u = url.strip()
    u = re.sub(r"#.*$", "", u)  # fragment
    # sorgu parametrelerinden izleyicileri temizle.
    # DIKKAT: sondaki "/" temizligi, sorgu eklenmeden ONCE yol kismina
    # uygulanmali -- aksi halde ".../x/?id=5" sonda "/" ile bitmedigi
    # icin temizlenmeden kalir ve ".../x?id=5" ile ayni sayilmaz.
    base, sep, query = u.partition("?")
    base = re.sub(r"/+$", "", base)
    if sep:
        kept = []
        for part in query.split("&"):
            if not part:
                continue
            key = part.split("=", 1)[0].lower()
            if key.startswith("utm_") or key in {"fbclid", "gclid", "ref", "_ga"}:
                continue
            kept.append(part)
        u = base + ("?" + "&".join(kept) if kept else "")
    else:
        u = base
    # sema + host kucuk harfe
    m = re.match(r"^(https?)://([^/]+)(.*)$", u, flags=re.I)
    if m:
        u = f"{m.group(1).lower()}://{m.group(2).lower()}{m.group(3)}"
    return u


def make_item_id(source_id: str, url: str, title: str) -> str:
    """Deterministik kimlik. AYNI haber tekrar toplandiginda AYNI id
    uretilir -- boylece idempotent yazma mumkun olur (PULSE'un idempotent
    skip ilkesiyle ayni mantik).

    URL bos olabilecegi icin (bazi kaynaklar) basliga da dusulur."""
    basis = f"{source_id}|{normalize_url(url)}|{title.strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate(item: NewsItem) -> None:
    """FAIL-CLOSED dogrulama. Ihlalde ContractViolation firlatir --
    collector bunu yakalayip kaydi REJECTED olarak isaretler, sessizce
    atmaz."""
    if item.contract_version != CONTRACT_VERSION:
        raise ContractViolation(
            f"contract_version {item.contract_version!r} != {CONTRACT_VERSION!r}"
        )
    if not item.item_id:
        raise ContractViolation("item_id bos")
    if not item.source_id:
        raise ContractViolation("source_id bos")
    if item.source_kind not in VALID_SOURCE_KINDS:
        raise ContractViolation(f"gecersiz source_kind: {item.source_kind!r}")
    if item.match_confidence not in VALID_MATCH_CONFIDENCE:
        raise ContractViolation(f"gecersiz match_confidence: {item.match_confidence!r}")
    if not item.title or not item.title.strip():
        raise ContractViolation("title bos")
    if not item.url or not item.url.strip():
        raise ContractViolation("url bos -- kaynaga geri donulemeyen kayit kabul edilmez")
    if not re.match(r"^https?://[^/\s]+(?:/|$)", item.url.strip(), flags=re.I):
        raise ContractViolation("url yalnızca http/https ve geçerli host içermeli")
    if len(item.summary) > MAX_SUMMARY_CHARS:
        raise ContractViolation(
            f"summary {len(item.summary)} karakter > {MAX_SUMMARY_CHARS} "
            f"(telif siniri -- tam metin saklanmaz)"
        )
    if not item.collected_at:
        raise ContractViolation("collected_at bos")
    for t in item.tickers:
        if not re.fullmatch(r"[A-Z0-9]{3,6}", t):
            raise ContractViolation(f"gecersiz ticker formati: {t!r}")


def clip_summary(text: Optional[str]) -> str:
    """Ozeti telif sinirinda keser + HTML etiketlerini temizler."""
    if not text:
        return ""
    # Bazı RSS sağlayıcıları entity'leri çift encode eder (örn.
    # &amp;#039;). En fazla üç tur çözerek kullanıcıya ham entity
    # metni göstermeyi engelleriz; sabit tur sayısı kötü niyetli
    # girdilerde sınırsız çözüm döngüsünü de önler.
    clean = str(text)
    for _ in range(3):
        decoded = html.unescape(clean)
        if decoded == clean:
            break
        clean = decoded
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > MAX_SUMMARY_CHARS:
        clean = clean[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return clean
