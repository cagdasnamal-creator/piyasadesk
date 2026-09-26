"""
Genel RSS adaptoru -- Bigpara, Mynet Finans, Bloomberg HT, Dunya vb.

Neden RSS (scraping degil):
  - Yayincinin ACIKCA makine tuketimi icin sundugu kanal
  - Baslik + kisa ozet + link verir; tam metin VERMEZ -- bu tam olarak
    bizim telif sinirimiza uyuyor (NEWS_CONTRACT_V1, MAX_SUMMARY_CHARS)
  - Sayfa HTML'i degistiginde kirilmaz

Bir RSS akisi genellikle sembol alani TASIMAZ -- bu yuzden buradan gelen
tum kayitlar match_confidence=INFERRED olur (baslik+ozet metninden
cikarim). KAP ise EXACT verir. Bu ayrim UI'da gosterilir.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests

from haber.contract import (
    CONTRACT_VERSION, MATCH_INFERRED, NewsItem, SOURCE_KIND_MEDIA,
    ContractViolation, clip_summary, make_item_id, utc_now_iso, validate,
)
from haber.sources.base import (
    FEED_EMPTY_SUSPECT, FEED_EXPECTED_EMPTY, FEED_UNPARSEABLE,
    FEED_VALID_NONEMPTY, FetchResult, NewsSource,
)
from haber.tickers import extract_tickers_with_aliases, load_company_aliases

USER_AGENT = "HisseHaberMerkezi/1.0 (kisisel arastirma araci)"
DEFAULT_TIMEOUT = 20


def _parse_published(entry) -> Optional[str]:
    """RSS tarih alanini ISO8601 UTC'ye cevirir. Cevrilemezse None --
    UYDURULMAZ (PULSE'un 'fabricate etme' ilkesi)."""
    for attr in ("published_parsed", "updated_parsed"):
        tm = getattr(entry, attr, None)
        if tm:
            try:
                return datetime(*tm[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
    return None


class RssNewsSource(NewsSource):
    source_kind = SOURCE_KIND_MEDIA

    def __init__(self, source_id: str, feed_url: str, timeout: int = DEFAULT_TIMEOUT):
        self.source_id = source_id
        self.feed_url = feed_url
        self.timeout = timeout

    def fetch(self, universe: set[str]) -> FetchResult:
        t0 = time.monotonic()
        try:
            resp = requests.get(
                self.feed_url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as e:
            return FetchResult(
                source_id=self.source_id, ok=False, http_status=None, raw_text=None,
                items=[], error=f"{type(e).__name__}: {e}",
                elapsed_seconds=time.monotonic() - t0,
            )

        elapsed = time.monotonic() - t0
        if resp.status_code != 200:
            return FetchResult(
                source_id=self.source_id, ok=False, http_status=resp.status_code,
                raw_text=resp.text, items=[],
                error=f"HTTP {resp.status_code}", elapsed_seconds=elapsed,
            )

        return self.parse(resp.text, universe, http_status=resp.status_code, elapsed=elapsed)

    def parse(self, raw_text: str, universe: set[str],
              http_status: Optional[int] = 200,
              elapsed: Optional[float] = None) -> FetchResult:
        """Ham RSS metnini NewsItem'lara cevirir. Ag cagrisi YAPMAZ --
        bu sayede test edilebilir ve kaydedilmis ham yanitlar yeniden
        islenebilir (reprocessing).

        KRITIK: HTTP 200 donmus olmasi, gelenin GERCEKTEN bir RSS akisi
        oldugu anlamina GELMEZ. Yayinci hata sayfasi (HTML), Cloudflare
        challenge'i veya bos govde donebilir. feedparser bunlari
        sikayetsiz 'sifir kayitli akis' gibi gosterir -- bu, bozuk bir
        kaynagi sessizce saglikli gostermek olurdu (PULSE'un
        UNEXPLAINED_EMPTY dersi). Bu yuzden asagida akisin GERCEKTEN
        akis olup olmadigini ayrica dogruluyoruz."""
        parsed = feedparser.parse(raw_text)
        entries = list(parsed.entries)

        # Akis yapisi gercekten var mi? Gecerli bir RSS/Atom akisinda
        # feed basligi veya en az bir kayit bulunur.
        feed_obj = getattr(parsed, "feed", None)
        has_feed_structure = bool(feed_obj and (
            getattr(feed_obj, "title", None) or getattr(feed_obj, "link", None)
        ))
        bozo = bool(getattr(parsed, "bozo", 0))
        looks_like_html = bool(re.search(r"<\s*(!doctype\s+html|html|body)\b",
                                          (raw_text or "")[:2000], re.I))

        if not entries:
            if looks_like_html or (bozo and not has_feed_structure):
                reason = "HTML sayfasi geldi" if looks_like_html else "ayristirilabilir akis degil"
                return FetchResult(
                    source_id=self.source_id, ok=False, http_status=http_status,
                    raw_text=raw_text, items=[],
                    error=(f"HTTP {http_status} fakat govde RSS DEGIL ({reason}). "
                           f"Besleme adresi degismis olabilir."),
                    elapsed_seconds=elapsed, feed_status=FEED_UNPARSEABLE,
                )
            if not has_feed_structure:
                return FetchResult(
                    source_id=self.source_id, ok=False, http_status=http_status,
                    raw_text=raw_text, items=[],
                    error=("Akis yapisi dogrulanamadi ve hic kayit yok -- "
                           "bos kabul edilmiyor (supheli)."),
                    elapsed_seconds=elapsed, feed_status=FEED_EMPTY_SUSPECT,
                )
            # Gecerli akis, gercekten bos: bu MESRU bir durum.
            return FetchResult(
                source_id=self.source_id, ok=True, http_status=http_status,
                raw_text=raw_text, items=[], elapsed_seconds=elapsed,
                feed_status=FEED_EXPECTED_EMPTY,
            )

        items: list[NewsItem] = []
        rejected = 0
        collected_at = utc_now_iso()
        aliases = load_company_aliases()   # sirket adi -> kod eslemesi

        for entry in entries:
            title = (getattr(entry, "title", "") or "").strip()
            for _ in range(3):
                decoded_title = html.unescape(title)
                if decoded_title == title:
                    break
                title = decoded_title
            link = (getattr(entry, "link", "") or "").strip()
            raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            summary = clip_summary(raw_summary)

            tickers = extract_tickers_with_aliases(f"{title} {summary}", universe, aliases)

            item = NewsItem(
                item_id=make_item_id(self.source_id, link, title),
                contract_version=CONTRACT_VERSION,
                source_id=self.source_id,
                source_kind=self.source_kind,
                tickers=tickers,
                match_confidence=MATCH_INFERRED,
                title=title,
                summary=summary,
                url=link,
                published_at=_parse_published(entry),
                collected_at=collected_at,
            )
            try:
                validate(item)
            except ContractViolation:
                rejected += 1
                continue
            items.append(item)

        return FetchResult(
            source_id=self.source_id, ok=True, http_status=http_status,
            raw_text=raw_text, items=items, elapsed_seconds=elapsed,
            item_count_raw=len(entries), item_count_rejected=rejected,
            feed_status=FEED_VALID_NONEMPTY,
        )
