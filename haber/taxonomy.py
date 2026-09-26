"""
Deterministik haber kategorisi + bilgi-onemi siniflandirmasi.

AMAC:
  - Kullaniciya uzun akista hangi haber TURU ile karsilastigini gostermek.
  - Sirket-ozel / resmi / maddi bildirimleri rutin ve genel haberlerden
    ayirmaya yardim etmek.

KRITIK SINIR -- NEWS != SIGNAL:
  Buradaki `importance_level` bir AL/SAT skoru, sentiment, fiyat etkisi veya
  beklenen getiri DEGILDIR. Yalnizca haberin bilgi yogunlugu / sirket-ozel
  maddilik ihtimalini acik, deterministik kurallarla siniflandirir.

Tasarim:
  - NewsItem degistirilmez; turetilen metadata API okuma aninda hesaplanir.
  - Her sonuc `reasons` ile aciklanabilir.
  - Suphede kategori OTHER kalir; agresif tahmin yapilmaz.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from haber.contract import NewsItem, SOURCE_KIND_MEDIA, SOURCE_KIND_REGULATORY
from haber.kap_subjects import CLASS_MATERIAL, CLASS_ROUTINE

# --- Kategori kimlikleri -------------------------------------------------
CAT_FINANCIALS = "FINANCIALS"
CAT_CONTRACT_TENDER = "CONTRACT_TENDER"
CAT_CAPITAL_ACTION = "CAPITAL_ACTION"
CAT_DIVIDEND = "DIVIDEND"
CAT_BUYBACK = "BUYBACK"
CAT_MNA = "MNA"
CAT_INVESTMENT_OPERATION = "INVESTMENT_OPERATION"
CAT_LEGAL_REGULATORY = "LEGAL_REGULATORY"
CAT_MANAGEMENT_GOVERNANCE = "MANAGEMENT_GOVERNANCE"
CAT_DEBT_CREDIT = "DEBT_CREDIT"
CAT_MARKET_MACRO = "MARKET_MACRO"
CAT_OTHER = "OTHER"

CATEGORY_LABELS = {
    CAT_FINANCIALS: "Finansal Sonuç",
    CAT_CONTRACT_TENDER: "İhale / Sözleşme",
    CAT_CAPITAL_ACTION: "Sermaye İşlemi",
    CAT_DIVIDEND: "Temettü",
    CAT_BUYBACK: "Pay Geri Alımı",
    CAT_MNA: "Birleşme / Satın Alma",
    CAT_INVESTMENT_OPERATION: "Yatırım / Operasyon",
    CAT_LEGAL_REGULATORY: "Hukuk / Regülasyon",
    CAT_MANAGEMENT_GOVERNANCE: "Yönetim / Kurumsal",
    CAT_DEBT_CREDIT: "Borçlanma / Kredi",
    CAT_MARKET_MACRO: "Makro / Piyasa",
    CAT_OTHER: "Diğer",
}

# Onem seviyesi -- yatirim yonu DEGIL.
IMP_LOW = "LOW"
IMP_NOTICE = "NOTICE"
IMP_IMPORTANT = "IMPORTANT"
IMP_HIGH = "HIGH"

IMPORTANCE_LABELS = {
    IMP_LOW: "Düşük Öncelik",
    IMP_NOTICE: "Dikkat",
    IMP_IMPORTANT: "Önemli",
    IMP_HIGH: "Yüksek Önem",
}

# Oncelik sirasiyla kontrol edilir. Bir haber birden fazla kaliba uyarsa
# en spesifik kategori kazanir.
CATEGORY_PATTERNS = [
    (CAT_DIVIDEND, [
        "temettu", "kar payi", "kar dagitim", "nakit kar payi",
    ]),
    (CAT_BUYBACK, [
        "pay geri alim", "hisse geri alim", "geri alim program",
    ]),
    (CAT_MNA, [
        "birlesme", "devralma", "satın alma", "satin alma", "pay devri",
        "varlik devri", "ortaklik devri", "bolunme",
    ]),
    (CAT_CAPITAL_ACTION, [
        "sermaye artirim", "sermaye azalt", "bedelli", "bedelsiz",
        "tahsisli sermaye", "ruchan", "halka arz", "esas sozlesme",
    ]),
    (CAT_FINANCIALS, [
        "finansal rapor", "finansal tablo", "bilanco", "bilanço",
        "net kar", "net zarar", "favok", "favök", "ciro", "satis gelir",
        "faaliyet kari", "faaliyet zarari", "donem kari", "donem zarari",
    ]),
    (CAT_CONTRACT_TENDER, [
        "ihale", "sozlesme", "sözleşme", "siparis", "sipariş",
        "yeni is iliskisi", "yeni iş ilişkisi", "proje kazandi",
        "proje kazandı", "is aldi", "iş aldı",
    ]),
    (CAT_LEGAL_REGULATORY, [
        "spk", "rekabet kurulu", "dava", "mahkeme", "ceza", "sorusturma",
        "soruşturma", "vergi incele", "ruhsat", "lisans iptal", "idari para",
        "regulasyon", "regülasyon",
    ]),
    (CAT_DEBT_CREDIT, [
        "kredi", "borclanma", "borçlanma", "tahvil", "bono", "sendikasyon",
        "refinansman", "finansman sozlesmesi", "finansman sözleşmesi",
    ]),
    (CAT_INVESTMENT_OPERATION, [
        "yatirim", "yatırım", "fabrika", "tesis", "kapasite", "uretim",
        "üretim", "maden", "rezerv", "lisans", "faaliyete basla",
        "faaliyete başla", "acilis", "açılış", "ihracat", "sevkiyat",
    ]),
    (CAT_MANAGEMENT_GOVERNANCE, [
        "yonetim kurulu", "yönetim kurulu", "genel mudur", "genel müdür",
        "ust yonetim", "üst yönetim", "genel kurul", "bagimsiz yonetim",
        "bağımsız yönetim", "atama", "istifa",
    ]),
    (CAT_MARKET_MACRO, [
        "merkez bankasi", "merkez bankası", "faiz karari", "faiz kararı",
        "enflasyon", "tuik", "tüik", "dolar", "euro", "altin", "altın",
        "petrol", "fed", "ecb", "resesyon", "buyume", "büyüme",
        "issizlik", "işsizlik", "dis ticaret", "dış ticaret",
    ]),
]

CATEGORY_WEIGHTS = {
    CAT_FINANCIALS: 25,
    CAT_CONTRACT_TENDER: 20,
    CAT_CAPITAL_ACTION: 25,
    CAT_DIVIDEND: 20,
    CAT_BUYBACK: 18,
    CAT_MNA: 25,
    CAT_INVESTMENT_OPERATION: 15,
    CAT_LEGAL_REGULATORY: 20,
    CAT_MANAGEMENT_GOVERNANCE: 10,
    CAT_DEBT_CREDIT: 15,
    CAT_MARKET_MACRO: 0,
    CAT_OTHER: 0,
}


def _norm(text: str) -> str:
    """Turkce/Unicode toleransli eslesme icin sade metin."""
    s = (text or "").casefold().replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Pattern tablosunu bir kez normalize et.
_NORM_PATTERNS = [
    (cat, tuple(_norm(p) for p in pats)) for cat, pats in CATEGORY_PATTERNS
]


@dataclass(frozen=True)
class Classification:
    category: str
    category_label: str
    importance_level: str
    importance_label: str
    importance_points: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "category_label": self.category_label,
            "importance_level": self.importance_level,
            "importance_label": self.importance_label,
            "importance_points": self.importance_points,
            "reasons": list(self.reasons),
        }


def classify_category(item: NewsItem) -> str:
    text = _norm(f"{item.title} {item.summary}")
    if not text:
        return CAT_OTHER
    padded = f" {text} "
    for cat, patterns in _NORM_PATTERNS:
        for p in patterns:
            # Cogu kalip cok kelimeli; word-boundary benzeri bosluk kontrolu
            # kisa tokenlarda yanlis pozitifleri azaltir.
            if f" {p} " in padded or (" " in p and p in text):
                return cat
    # Genel/dunya medya haberi ticker'siz ise macro/piyasa saymak UI icin
    # daha anlamli; ancak sirket haberi siniflandirilamadiysa OTHER kalir.
    if item.source_kind == SOURCE_KIND_MEDIA and not (item.tickers or ()):
        return CAT_MARKET_MACRO
    return CAT_OTHER


def _level(points: int) -> str:
    if points >= 65:
        return IMP_HIGH
    if points >= 45:
        return IMP_IMPORTANT
    if points >= 25:
        return IMP_NOTICE
    return IMP_LOW


def classify(item: NewsItem) -> Classification:
    category = classify_category(item)
    points = 0
    reasons: list[str] = []

    if item.source_kind == SOURCE_KIND_REGULATORY:
        points += 25
        reasons.append("resmî KAP bildirimi")
    elif item.source_kind == SOURCE_KIND_MEDIA:
        reasons.append("medya haberi")

    if item.match_confidence == "EXACT" and item.tickers:
        points += 10
        reasons.append("sembol kaynakta yapısal olarak eşleşti")
    elif item.tickers:
        points += 5
        reasons.append("şirket sembolü metinden eşleşti")

    if item.tickers:
        points += 10
        reasons.append("şirkete/sembole özgü")
    else:
        points -= 20
        reasons.append("genel piyasa haberi")

    weight = CATEGORY_WEIGHTS.get(category, 0)
    if weight:
        points += weight
        reasons.append(f"{CATEGORY_LABELS[category]} türü")

    kap_class = (item.extra or {}).get("kap_subject_class")
    if kap_class == CLASS_ROUTINE:
        points -= 40
        reasons.append("rutin/teknik KAP türü")
    elif kap_class == CLASS_MATERIAL:
        points += 10
        reasons.append("KAP konusu maddi/kurumsal türde")

    # Sinirlari stabil tut; UI'da puan yalnizca aciklanabilirlik icin
    # tasinir, yatirim skoru olarak kullanilmaz.
    points = max(0, min(100, points))
    level = _level(points)

    return Classification(
        category=category,
        category_label=CATEGORY_LABELS[category],
        importance_level=level,
        importance_label=IMPORTANCE_LABELS[level],
        importance_points=points,
        reasons=tuple(reasons),
    )


def category_options() -> list[dict]:
    return [{"value": k, "label": v} for k, v in CATEGORY_LABELS.items()]


def importance_options() -> list[dict]:
    # Dusukten yuksege degil, kullanici filtresinde daha dogal gorunsun diye
    # yuksekten rutine.
    order = (IMP_HIGH, IMP_IMPORTANT, IMP_NOTICE, IMP_LOW)
    return [{"value": k, "label": IMPORTANCE_LABELS[k]} for k in order]
