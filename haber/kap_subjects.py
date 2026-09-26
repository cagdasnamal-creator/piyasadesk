"""
KAP bildirim KONUSU siniflandirmasi -- rutin / onemli / diger.

AMAC: KAP'in hacmi buyuk ama bilgi degeri dusuk bildirimleri var
("Pay Bazinda Devre Kesici Bildirimi" gibi -- gun icinde onlarca kez).
Bunlar kaybedilmemeli ama varsayilan gorunumu bogmamali.

ONEMLI SINIR -- bu bir DEGER YARGISI DEGIL:
    Burada siniflandirilan sey bildirimin TURU'dur, hissenin iyi/kotu
    olusu DEGIL. "Devre kesici" rutin bir bildirim turudur; hisse icin
    olumlu mu olumsuz mu oldugu hakkinda hicbir sey soylemez.
    NEWS != SIGNAL sinirina dokunmaz; sentiment ALANINDAN farkli olarak
    bu, kaynagin kendi bildirim basligindan TURETILEN olgusal bir
    kategoridir.

Sonuc `extra["kap_subject_class"]` icinde saklanir -- contract'in
top-level alanlarina DOKUNULMAZ.
"""
from __future__ import annotations

import re

CLASS_ROUTINE = "ROUTINE"      # yuksek hacim, dusuk bilgi
CLASS_MATERIAL = "MATERIAL"    # ozel durum, finansal, kurumsal aksiyon
CLASS_OTHER = "OTHER"          # siniflandirilamadi

# Rutin/teknik bildirim basliklari. Kucuk harfe cevrilmis baslikta
# ARANIR (substring). Liste muhafazakar tutuldu -- suphede kalirsan
# MATERIAL/OTHER tarafinda birak, cunku bir bildirimi yanlislikla
# "rutin" diye gizlemek, gereksiz bir bildirimi gostermekten daha kotu.
ROUTINE_PATTERNS = [
    "devre kesici",
    "piyasa yapicilig", "piyasa yapıcılığ",
    "tedbir", "tedbir sistemi",
    "islem sirasi", "işlem sırası",
    "varant", "sertifika",
    "borclanma araclari alim satim", "borçlanma araçları alım satım",
    "alim satim islemleri", "alım satım işlemleri",
    "fon fiyat", "portfoy dagilim", "portföy dağılım",
    "haftalik rapor", "haftalık rapor",
    "gunluk bulten", "günlük bülten",
    "bulten", "bülten",
]

# Yuksek degerli bildirim basliklari.
MATERIAL_PATTERNS = [
    "ozel durum", "özel durum",
    "kar payi", "kâr payı", "kar pay",
    "temettu", "temettü",
    "sermaye artirim", "sermaye artırım", "sermaye azalt",
    "birlesme", "birleşme", "devralma", "bolunme", "bölünme",
    "yeni is iliskisi", "yeni iş ilişkisi",
    "ihale",
    "finansal rapor", "finansal tablo", "bilanco", "bilanço",
    "faaliyet raporu",
    "genel kurul",
    "pay geri alim", "pay geri alım",
    "yonetim kurulu", "yönetim kurulu",
    "sozlesme", "sözleşme",
    "yatirim karari", "yatırım kararı",
    "halka arz",
    "esas sozlesme", "esas sözleşme",
]


def _norm(text: str) -> str:
    """Turkce-guvenli normalizasyon.

    DIKKAT: Python'da "İ".lower() IKI karakter uretir (u0069 + u0307
    birlesen nokta). Bu yuzden once buyuk Turkce harfler ASCII'ye
    cevrilir, SONRA kucultulur -- aksi halde "İhale" -> "i̇hale" olur ve
    "ihale" kalibiyla ESLESMEZ. (Bu gercek bir hatayla yakalandi.)"""
    t = (text or "")
    t = t.translate(str.maketrans("ÇĞİÖŞÜÂÎ", "CGIOSUAI"))
    t = t.lower()
    t = t.translate(str.maketrans("çğıöşüâî", "cgiosuai"))
    return t.replace("\u0307", "")  # artik birlesen nokta kalmasin


def classify_subject(title: str) -> str:
    """Bildirim basligindan TUR sinifi cikarir.

    MATERIAL once kontrol edilir: bir baslik hem "genel kurul" hem
    "bulten" gecerse, onemli olan agir basmali."""
    t = _norm(title)
    if not t.strip():
        return CLASS_OTHER

    for pat in MATERIAL_PATTERNS:
        if _norm(pat) in t:
            return CLASS_MATERIAL
    for pat in ROUTINE_PATTERNS:
        if _norm(pat) in t:
            return CLASS_ROUTINE
    return CLASS_OTHER
