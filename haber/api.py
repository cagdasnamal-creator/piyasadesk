"""
READ-ONLY API -- bu process ASLA aga cikmaz.

PULSE'un "PULSE = read-only consumer, hicbir kosulda network'e cikmaz,
sadece local status dosyasi okur" ilkesinin birebir uygulanmasi.
Burada `requests` ya da baska bir ag kutuphanesi IMPORT BILE EDILMEZ --
bu bir test tarafindan da dogrulanir.

Calistirma:
    uvicorn haber.api:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import re
import unicodedata

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from haber import health as health_mod
from haber import store
from haber.contract import CONTRACT_VERSION
from haber.tickers import load_universe
from haber.taxonomy import classify as classify_news, category_options, importance_options

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="PiyasaDesk", version="1.1")


def _sort_key(item):
    """En yeni once. published_at yoksa collected_at'e duser."""
    return item.published_at or item.collected_at or ""


def _dedupe_title(text: str) -> str:
    """Ayni medya basligini kaynaklar arasi guvenli sekilde gruplamak icin
    muhafazakar normalizasyon. Benzer ama farkli haberleri birlestirmez."""
    x = (text or "").casefold().replace("ı", "i")
    x = unicodedata.normalize("NFKD", x)
    x = "".join(ch for ch in x if not unicodedata.combining(ch))
    x = re.sub(r"[^a-z0-9]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def _importance_rank(level: str) -> int:
    return {"HIGH": 4, "IMPORTANT": 3, "NOTICE": 2, "LOW": 1}.get(level, 0)


@app.get("/api/health")
def api_health():
    state = store.read_state()
    h = health_mod.overall_health(state)
    return {
        "contract_version": CONTRACT_VERSION,
        "last_run_at": state.get("last_run_at"),
        "health": h,
    }


@app.get("/api/universe")
def api_universe():
    u = sorted(load_universe())
    return {"count": len(u), "tickers": u}


@app.get("/api/news")
def api_news(
    ticker: Optional[str] = Query(None, description="Hisse kodu, orn. ESCOM"),
    tickers: Optional[str] = Query(None, description="Virgulle ayrilmis hisse kodlari"),
    limit: int = Query(50, ge=1, le=500),
    source_kind: Optional[str] = Query(None, description="REGULATORY / MEDIA / SOCIAL"),
    match: Optional[str] = Query(None, description="EXACT / INFERRED"),
    hide_routine: bool = Query(False, description="KAP rutin bildirimlerini gizle"),
    hide_world: bool = Query(False, description="Sembolsuz genel/dunya medya haberlerini gizle"),
    world_only: bool = Query(False, description="Yalnizca sembolsuz genel/dunya medya haberlerini getir"),
    category: Optional[str] = Query(None, description="Turetilmis haber kategorisi"),
    importance: Optional[str] = Query(None, description="LOW / NOTICE / IMPORTANT / HIGH"),
    sort: str = Query("latest", description="latest / importance_desc / importance_asc"),
    dedupe: bool = Query(True, description="Ayni medya basliklarini kaynaklar arasi grupla"),
):
    """Haberleri dondurur.

    Izleme listeleri SUNUCUDA tutulmaz. Tarayici kendi listesini localStorage'da
    saklar ve bu uca yalnızca filtrelenecek sembolleri `tickers=` ile yollar.
    Boylece baska ziyaretciler birbirinin listelerini goremez/silemez.
    `ticker` verilirse tek-sembol sorgusu olarak `tickers` parametresinden onceliklidir.
    """
    items = store.read_all()
    applied_tickers = None

    if ticker:
        t = ticker.strip().upper()
        applied_tickers = [t]
        items = [i for i in items if t in (i.tickers or ())]
    elif tickers is not None:
        universe = load_universe()
        requested = []
        for raw in tickers.split(','):
            t = raw.strip().upper()
            if not t or t in requested:
                continue
            if len(requested) >= 200:
                break
            if universe and t not in universe:
                continue
            requested.append(t)
        applied_tickers = requested
        if not requested:
            return {
                "contract_version": CONTRACT_VERSION,
                "query": {"tickers": tickers, "limit": limit,
                          "source_kind": source_kind, "match": match},
                "applied_tickers": [],
                "total_matched": 0, "returned": 0, "items": [],
                "note": "Gecerli sembol bulunamadi.",
            }
        wanted = set(requested)
        items = [i for i in items if wanted & set(i.tickers or ())]

    if source_kind:
        sk = source_kind.strip().upper()
        items = [i for i in items if i.source_kind == sk]
    if match:
        m = match.strip().upper()
        items = [i for i in items if i.match_confidence == m]
    if hide_routine:
        # KAP'in yuksek hacimli/dusuk bilgili bildirim TURLERI (devre
        # kesici vb.) gizlenir. Bu bir deger yargisi degil, bildirim
        # turu siniflandirmasidir (bkz. haber/kap_subjects.py).
        items = [i for i in items
                 if (i.extra or {}).get("kap_subject_class") != "ROUTINE"]

    # "Dunya/genel" haber tanimi: medya kaydi olup hicbir BIST sembolune
    # eslesmeyen haber. Varsayilan ana akis bunlari gizleyebilir; isteyen
    # UI'daki "Dunya haberleri" filtresinden gorebilir.
    def _is_world_item(i):
        return i.source_kind == "MEDIA" and not (i.tickers or ())

    if world_only:
        items = [i for i in items if _is_world_item(i)]
    elif hide_world:
        items = [i for i in items if not _is_world_item(i)]

    # Kategori/onem metadata'si depoya yazilmaz; immutable NewsItem uzerinden
    # okuma aninda deterministik olarak turetilir. NEWS != SIGNAL siniri korunur.
    enriched = [(i, classify_news(i)) for i in items]
    if category:
        cat = category.strip().upper()
        enriched = [(i, c) for i, c in enriched if c.category == cat]
    if importance:
        imp = importance.strip().upper()
        enriched = [(i, c) for i, c in enriched if c.importance_level == imp]

    sort_mode = (sort or "latest").strip().lower()
    # Önce en yeniye göre sırala. Python sort stabil olduğu için önem
    # sıralaması sonradan uygulandığında aynı önem/puan içindeki haberler
    # yine en yeni -> eski kalır. Özellikle importance_asc modunda eski
    # haberlerin yanlışlıkla üste çıkmasını önler.
    enriched.sort(key=lambda pair: _sort_key(pair[0]), reverse=True)
    if sort_mode == "importance_desc":
        enriched.sort(key=lambda pair: (_importance_rank(pair[1].importance_level), pair[1].importance_points), reverse=True)
    elif sort_mode == "importance_asc":
        enriched.sort(key=lambda pair: (_importance_rank(pair[1].importance_level), pair[1].importance_points))
    else:
        sort_mode = "latest"

    # Kaynaklar arasi ayni MEDIA basligi tek kartta toplanir. KAP kayitlari
    # resmi belge oldugu icin ASLA medya ile birlestirilmez. Baslik
    # normalizasyonu muhafazakardir: sadece birebir normalize baslik + ayni
    # ticker seti gruplanir; semantik/AI benzerligi kullanilmaz.
    grouped = []
    seen = {}
    if dedupe:
        for item, cls in enriched:
            if item.source_kind == "MEDIA":
                # Aynı genel başlık farklı günlerde yeniden kullanılabilir
                # ("Piyasalarda gün ortası" gibi). Gün kovası olmadan 7
                # günlük kayıtlar yanlışlıkla tek karta birleşiyordu.
                day = (item.published_at or item.collected_at or "")[:10]
                key = (item.source_kind, _dedupe_title(item.title), tuple(sorted(item.tickers or ())), day)
            else:
                key = None
            if key and key in seen:
                g = seen[key]
                # Aynı kaynağın aynı başlıklı iki ayrı URL/haberi olabilir;
                # sadece FARKLI kaynaklar arası dedupe yap.
                if item.source_id not in g["duplicate_sources"]:
                    g["duplicate_count"] += 1
                    g["duplicate_sources"].append(item.source_id)
                    continue
            rec = {"item": item, "cls": cls, "duplicate_count": 1, "duplicate_sources": [item.source_id]}
            grouped.append(rec)
            if key:
                seen[key] = rec
    else:
        grouped = [{"item": i, "cls": c, "duplicate_count": 1, "duplicate_sources": [i.source_id]} for i, c in enriched]

    total = len(grouped)
    grouped = grouped[:limit]

    out_items = []
    for rec in grouped:
        item, cls = rec["item"], rec["cls"]
        d = item.to_dict()
        d["classification"] = cls.to_dict()
        d["duplicate_count"] = rec["duplicate_count"]
        d["duplicate_sources"] = rec["duplicate_sources"]
        out_items.append(d)

    return {
        "contract_version": CONTRACT_VERSION,
        "query": {"ticker": ticker, "tickers": tickers, "limit": limit,
                  "source_kind": source_kind, "match": match,
                  "hide_routine": hide_routine,
                  "hide_world": hide_world, "world_only": world_only,
                  "category": category, "importance": importance,
                  "sort": sort_mode, "dedupe": dedupe},
        "applied_tickers": applied_tickers,
        "total_matched": total,
        "returned": len(out_items),
        "items": out_items,
    }


# ---------------------------------------------------------------------
# Izleme listeleri tarayiciya ozeldir (web/localStorage).
# Sunucuda ortak watchlist CRUD endpoint'i YOKTUR. Bu, public deploy'da
# ziyaretcilerin birbirinin listelerini gormesini/silmesini engeller.
# ---------------------------------------------------------------------

@app.get("/api/taxonomy")
def api_taxonomy():
    """UI icin deterministik kategori/onem secenekleri."""
    return {
        "categories": category_options(),
        "importance_levels": importance_options(),
        "note": "Önem seviyesi yatırım yönü/tavsiyesi değildir; bilgi yoğunluğu sınıflamasıdır.",
    }


@app.get("/api/stats")
def api_stats():
    items = store.read_all()
    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    tickers_seen: dict[str, int] = {}
    for i in items:
        by_source[i.source_id] = by_source.get(i.source_id, 0) + 1
        by_kind[i.source_kind] = by_kind.get(i.source_kind, 0) + 1
        for t in i.tickers or ():
            tickers_seen[t] = tickers_seen.get(t, 0) + 1
    top = sorted(tickers_seen.items(), key=lambda kv: kv[1], reverse=True)[:20]
    return {
        "total_items": len(items),
        "by_source": by_source,
        "by_source_kind": by_kind,
        "distinct_tickers": len(tickers_seen),
        "top_tickers": [{"ticker": t, "count": c} for t, c in top],
    }


@app.get("/manifest.json")
def manifest():
    """PWA manifest -- tarayicinin 'uygulama olarak yukle' teklifi icin."""
    f = WEB_DIR / "manifest.json"
    if not f.exists():
        return JSONResponse({"error": "manifest bulunamadi"}, status_code=404)
    return FileResponse(f, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    """Service worker KOK kapsamda sunulmali (/static/sw.js scope'u
    yalnizca /static/ olurdu, bu da yuklenebilirligi bozar)."""
    f = WEB_DIR / "sw.js"
    if not f.exists():
        return JSONResponse({"error": "sw bulunamadi"}, status_code=404)
    return FileResponse(f, media_type="application/javascript")


@app.get("/")
def index():
    idx = WEB_DIR / "index.html"
    if not idx.exists():
        return JSONResponse({"error": "web/index.html bulunamadi"}, status_code=404)
    return FileResponse(idx)


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
