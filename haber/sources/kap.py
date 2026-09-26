"""
KAP (Kamuyu Aydinlatma Platformu) adaptoru -- resmi/yasal bildirimler.

Neden ayri ve neden REGULATORY:
  - KAP bildirimi sembolu YAPISAL bir alanda verir -> match_confidence=EXACT
    (haber sitelerinin metin-cikarimli INFERRED eslesmesinden farkli)
  - Yasal bildirim, medya yorumundan farkli bir guven seviyesindedir;
    UI ve ileride PULSE bu ikisini AYIRT EDEBILMELI

!!! DIKKAT -- ILK CALISTIRMADA DOGRULANMASI GEREKEN TEK YER BURASI !!!
KAP'in public uc noktasi ve JSON alan adlari zaman icinde degisebilir.
Bu adaptor:
  - uc noktayi KONFIGURE EDILEBILIR birakir (endpoint parametresi)
  - alan adlarini ESNEK eslestirme ile okur (asagidaki _pick)
  - beklenmeyen sema gelirse SESSIZCE BOS DONMEZ, acik hata dondurur
Ilk gercek calistirmada bos/hatali sonuc gelirse, tek duzeltilecek yer
_parse_records() icindeki alan adlaridir.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from haber.contract import (
    CONTRACT_VERSION, MATCH_EXACT, NewsItem, SOURCE_KIND_REGULATORY,
    ContractViolation, clip_summary, make_item_id, utc_now_iso, validate,
)
from haber.kap_subjects import classify_subject
from haber.sources.base import FetchResult, NewsSource

USER_AGENT = "HisseHaberMerkezi/1.0 (kisisel arastirma araci)"
DEFAULT_TIMEOUT = 25

# KAP bildirim detay sayfasi -- disclosureIndex ile link kurulur.
KAP_ITEM_URL_TEMPLATE = "https://www.kap.org.tr/tr/Bildirim/{index}"

# GERCEK uc nokta (dogrulandi): KAP bir Next.js SPA'si ve arkasinda
# kimlik dogrulamasiz JSON REST API var. Bildirim sorgu ekraninin
# kullandigi uc nokta budur.
#   POST, Content-Type: application/json
#   Referer header'i ZORUNLU (WAF bunu kontrol ediyor)
#   Govde: {"fromDate","toDate","mkkMemberOidList":[],"subjectList":[]}
#   Yanit: duz JSON dizisi (sarmalayici yok), en fazla 2000 kayit
DEFAULT_ENDPOINT = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
KAP_REFERER = "https://www.kap.org.tr/tr/bildirim-sorgu"

# Kac gunluk bildirim cekilsin. Kucuk tutuluyor: bu arac gunluk takip
# icin, tarihsel arsiv icin degil (RETENTION_POLICY_V1 ile tutarli).
DEFAULT_LOOKBACK_DAYS = 3


def _pick(d: dict, *names, default=None):
    """Alan adi varyasyonlarina dayanikli okuma (kapUrl/kap_url/url gibi)."""
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
        # camelCase <-> snake_case toleransi
        alt = re.sub(r"(?<!^)(?=[A-Z])", "_", n).lower()
        if alt in d and d[alt] not in (None, ""):
            return d[alt]
    return default


def _parse_stock_codes(value: Any, universe: set[str] | None = None) -> tuple[str, ...]:
    """KAP sembol alani string ("ESCOM, ARDYZ") veya liste olabilir.

    universe verilirse, evrende OLMAYAN kodlar ELENIR. Sebep (gercek
    hata): SPK bulteni gibi sirkete bagli OLMAYAN bildirimlerde sembol
    alani bos gelir; yanlislikla bir baslik metni okunursa oradan
    "KURULU" gibi sembol-gorunumlu kelimeler cikabilir. Evren kontrolu
    bunu yapisal olarak keser."""
    if not value:
        return ()
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[,;/\s]+", str(value))
    out = []
    for p in parts:
        s = p.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3,6}", s):
            continue
        if universe and s not in universe:
            continue          # evrende yok -> sembol degil
        if s not in out:
            out.append(s)
    return tuple(out)


def _parse_kap_date(value: Any) -> Optional[str]:
    """KAP tarihini ISO8601 UTC'ye cevirir. Cevrilemezse None -- UYDURULMAZ."""
    if not value:
        return None
    s = str(value).strip()
    # epoch ms
    if re.fullmatch(r"\d{13}", s):
        try:
            return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).isoformat()
        except Exception:
            return None
    # KAP saatleri Turkiye yerelidir (UTC+3, DST yok). Naive parse edip
    # UTC+3 etiketi takiyoruz, sonra UTC'ye ceviriyoruz.
    tr_tz = timezone(timedelta(hours=3))
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=tr_tz).astimezone(timezone.utc).isoformat()
    return None


class KapNewsSource(NewsSource):
    source_id = "KAP"
    source_kind = SOURCE_KIND_REGULATORY

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: int = DEFAULT_TIMEOUT,
                 lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.endpoint = endpoint
        self.timeout = timeout
        self.lookback_days = lookback_days

    def fetch(self, universe: set[str]) -> FetchResult:
        t0 = time.monotonic()
        today = datetime.now(timezone(timedelta(hours=3))).date()
        payload = {
            "fromDate": (today - timedelta(days=self.lookback_days)).isoformat(),
            "toDate": today.isoformat(),
            "mkkMemberOidList": [],   # bos = tum sirketler
            "subjectList": [],        # bos = tum konular
        }
        try:
            resp = requests.post(
                self.endpoint,
                json=payload,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    # WAF bu header'i kontrol ediyor -- olmadan reddedilir
                    "Referer": KAP_REFERER,
                },
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
                raw_text=resp.text, items=[], error=f"HTTP {resp.status_code}",
                elapsed_seconds=elapsed,
            )

        return self.parse(resp.text, universe, http_status=resp.status_code, elapsed=elapsed)

    def parse(self, raw_text: str, universe: set[str],
              http_status: Optional[int] = 200,
              elapsed: Optional[float] = None) -> FetchResult:
        """Ham KAP JSON'unu NewsItem'lara cevirir. Ag cagrisi YAPMAZ."""
        try:
            data = json.loads(raw_text)
        except Exception as e:
            return FetchResult(
                source_id=self.source_id, ok=False, http_status=http_status,
                raw_text=raw_text, items=[],
                error=f"JSON parse hatasi: {e}", elapsed_seconds=elapsed,
            )

        records = self._extract_records(data)
        if records is None:
            return FetchResult(
                source_id=self.source_id, ok=False, http_status=http_status,
                raw_text=raw_text, items=[],
                error=("Beklenmeyen KAP semasi -- kayit listesi bulunamadi. "
                       "kap.py::_extract_records icindeki alan adlari guncellenmeli."),
                elapsed_seconds=elapsed,
            )

        items: list[NewsItem] = []
        rejected = 0
        collected_at = utc_now_iso()

        for rec in records:
            if not isinstance(rec, dict):
                rejected += 1
                continue

            title = str(_pick(rec, "subject", "title", "basic", "disclosureType", default="") or "").strip()
            member = str(_pick(rec, "companyName", "memberName", "title", default="") or "").strip()
            if member and title and member not in title:
                title = f"{member} -- {title}"
            index = _pick(rec, "disclosureIndex", "index", "id")
            url = _pick(rec, "url", "link")
            if not url and index:
                url = KAP_ITEM_URL_TEMPLATE.format(index=index)

            tickers = _parse_stock_codes(
                _pick(rec, "stockCodes", "relatedStocks", "companyCode", "code"),
                universe,
            )
            summary = clip_summary(str(_pick(rec, "summary", "description", default="") or ""))

            item = NewsItem(
                item_id=make_item_id(self.source_id, str(url or ""), title),
                contract_version=CONTRACT_VERSION,
                source_id=self.source_id,
                source_kind=self.source_kind,
                tickers=tickers,
                match_confidence=MATCH_EXACT,  # KAP sembolu YAPISAL olarak verir
                title=title,
                summary=summary,
                url=str(url or ""),
                published_at=_parse_kap_date(_pick(rec, "publishDate", "publishDateTime", "date", "publishedAt")),
                collected_at=collected_at,
                extra={k: v for k, v in {
                    "disclosure_index": index,
                    "kap_subject_class": classify_subject(title),
                }.items() if v is not None},
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
            item_count_raw=len(records), item_count_rejected=rejected,
        )

    @staticmethod
    def _extract_records(data: Any) -> Optional[list]:
        """KAP yaniti duz liste de olabilir, sarmalanmis da. Bilinen
        sarmalayicilari dener; bulamazsa None doner (acik hata)."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("disclosures", "content", "data", "items", "result", "list"):
                v = data.get(key)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    for k2 in ("content", "data", "items"):
                        if isinstance(v.get(k2), list):
                            return v[k2]
        return None
