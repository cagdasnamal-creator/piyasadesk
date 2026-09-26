"""
Kaynak adaptoru tabani -- vendor-agnostic arayuz.

PULSE'un "vendor-agnostic interface arkasinda tek vendor" ilkesiyle ayni:
bugun KAP + birkac RSS var; yarin Twitter/X, Foreks, baska bir saglayici
eklenirse SADECE yeni bir adaptor dosyasi yazilir, collector/store/API
degismez.

Her adaptor iki sey dondurur:
  - ham yanit (provenance icin diske kaydedilir, ASLA uzerine yazilmaz)
  - contract'a uygun NewsItem listesi
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FetchResult:
    """Tek bir kaynak cekiminin acik sonucu. Basari/basarisizlik HER ZAMAN
    aciktir -- sessiz bos donus YOK (PULSE'un
    UNEXPLAINED_EMPTY_RETRYABLE dersi)."""
    source_id: str
    ok: bool
    http_status: Optional[int]
    raw_text: Optional[str]
    items: list                      # list[NewsItem]
    error: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    item_count_raw: int = 0          # parse edilen ham kayit sayisi
    item_count_rejected: int = 0     # contract ihlali nedeniyle elenen
    feed_status: Optional[str] = None  # bkz. asagidaki sabitler


# --- feed_status taksonomisi (PULSE'un durum taksonomisinden esinlenme) ---
# Bos bir sonucun NEDENI onemlidir; hepsini "basarili ama bos" saymak,
# bozuk bir kaynagi sessizce saglikli gostermek demektir.
FEED_VALID_NONEMPTY = "VALID_NONEMPTY"       # gecerli akis, kayit var
FEED_EXPECTED_EMPTY = "EXPECTED_EMPTY"       # gecerli akis, gercekten bos
FEED_UNPARSEABLE = "UNPARSEABLE"             # HTML/bozuk -- akis DEGIL
FEED_EMPTY_SUSPECT = "EMPTY_SUSPECT"         # bos + yapi supheli


class NewsSource(ABC):
    """Tum haber kaynaklarinin ortak arayuzu."""

    source_id: str
    source_kind: str

    @abstractmethod
    def fetch(self, universe: set[str]) -> FetchResult:
        """Kaynaktan ceker, NewsItem listesine cevirir.

        universe: gecerli sembol kumesi -- INFERRED ticker cikarimi icin.
        Bos evrenle cagrilirsa adaptor ticker cikarimi YAPMAMALI."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source_id={self.source_id!r}>"
