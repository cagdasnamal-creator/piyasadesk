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

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from haber import health as health_mod
from haber import store
from haber import watchlists as wl
from haber.contract import CONTRACT_VERSION
from haber.tickers import load_universe

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Hisse Haber Merkezi", version="1.0")


def _sort_key(item):
    """En yeni once. published_at yoksa collected_at'e duser."""
    return item.published_at or item.collected_at or ""


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
    watchlist: Optional[str] = Query(None, description="Izleme listesi adi"),
    limit: int = Query(50, ge=1, le=500),
    source_kind: Optional[str] = Query(None, description="REGULATORY / MEDIA / SOCIAL"),
    match: Optional[str] = Query(None, description="EXACT / INFERRED"),
    hide_routine: bool = Query(False, description="KAP rutin bildirimlerini gizle"),
):
    """Haberleri dondurur. ticker/watchlist verilmezse genel akis.

    ticker ve watchlist birlikte verilirse ticker onceliklidir (tek
    sembol, listeden daha dar bir sorgudur)."""
    items = store.read_all()
    applied_tickers = None

    if ticker:
        t = ticker.strip().upper()
        applied_tickers = [t]
        items = [i for i in items if t in (i.tickers or ())]
    elif watchlist:
        wl_tickers = wl.get_tickers(watchlist)
        if not wl_tickers:
            # Liste yok VEYA bos -- sessizce "tum haberler"e dusmek
            # YANILTICI olurdu (kullanici filtreledigini sanir).
            return {
                "contract_version": CONTRACT_VERSION,
                "query": {"watchlist": watchlist, "limit": limit,
                          "source_kind": source_kind, "match": match},
                "applied_tickers": [],
                "total_matched": 0, "returned": 0, "items": [],
                "note": "Liste bulunamadi veya bos.",
            }
        applied_tickers = wl_tickers
        wanted = set(wl_tickers)
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

    items.sort(key=_sort_key, reverse=True)
    total = len(items)
    items = items[:limit]

    return {
        "contract_version": CONTRACT_VERSION,
        "query": {"ticker": ticker, "watchlist": watchlist, "limit": limit,
                  "source_kind": source_kind, "match": match,
                  "hide_routine": hide_routine},
        "applied_tickers": applied_tickers,
        "total_matched": total,
        "returned": len(items),
        "items": [i.to_dict() for i in items],
    }


# ---------------------------------------------------------------------
# Izleme listeleri.
# DIKKAT: Bu uclar SADECE data/watchlists.json dosyasina yazar --
# toplanan veri deposuna (news.jsonl, raw/) ASLA dokunmaz. "Collector
# veri deposunun tek sahibidir" garantisi korunur (test ile dogrulanir).
# ---------------------------------------------------------------------

@app.get("/api/watchlists")
def api_watchlists():
    lists = wl.load_all()
    return {"count": len(lists), "watchlists": lists}


@app.put("/api/watchlists/{name}")
def api_watchlist_upsert(name: str, tickers: list[str] = Body(..., embed=True)):
    try:
        lists = wl.upsert(name, tickers, universe=load_universe())
    except wl.WatchlistError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "watchlists": lists}


@app.delete("/api/watchlists/{name}")
def api_watchlist_delete(name: str):
    return {"ok": True, "watchlists": wl.delete(name)}


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
