"""Hisse Haber Merkezi testleri -- gercek ag cagrisi YOK."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from haber import health as health_mod
from haber import store
from haber.contract import (
    CONTRACT_VERSION, MATCH_EXACT, MATCH_INFERRED, MAX_SUMMARY_CHARS,
    NewsItem, SOURCE_KIND_MEDIA, SOURCE_KIND_REGULATORY,
    ContractViolation, clip_summary, make_item_id, normalize_url,
    utc_now_iso, validate,
)
from haber.sources.kap import KapNewsSource
from haber.sources.rss import RssNewsSource
from haber.tickers import extract_tickers


UNIVERSE = {"ESCOM", "ARDYZ", "GARAN", "THYAO", "SASA", "AKBNK"}


def _item(**kw):
    base = dict(
        item_id="abc123", contract_version=CONTRACT_VERSION, source_id="TEST",
        source_kind=SOURCE_KIND_MEDIA, tickers=("ESCOM",), match_confidence=MATCH_INFERRED,
        title="Baslik", summary="ozet", url="https://example.com/x",
        published_at=None, collected_at=utc_now_iso(),
    )
    base.update(kw)
    return NewsItem(**base)


# --- CONTRACT ---------------------------------------------------------

def test_valid_item_passes():
    validate(_item())


def test_missing_url_rejected():
    """Kaynaga geri donulemeyen kayit kabul edilmez."""
    with pytest.raises(ContractViolation):
        validate(_item(url=""))


def test_oversized_summary_rejected_copyright_guard():
    with pytest.raises(ContractViolation):
        validate(_item(summary="x" * (MAX_SUMMARY_CHARS + 1)))


def test_clip_summary_enforces_limit_and_strips_html():
    out = clip_summary("<p>merhaba <b>dunya</b></p>" + "y" * 2000)
    assert len(out) <= MAX_SUMMARY_CHARS
    assert "<" not in out and ">" not in out


def test_bad_source_kind_rejected():
    with pytest.raises(ContractViolation):
        validate(_item(source_kind="WHATEVER"))


def test_bad_match_confidence_rejected():
    with pytest.raises(ContractViolation):
        validate(_item(match_confidence="MAYBE"))


def test_bad_ticker_format_rejected():
    with pytest.raises(ContractViolation):
        validate(_item(tickers=("escom-lower",)))


def test_item_id_is_deterministic():
    a = make_item_id("KAP", "https://x.com/a?utm_source=rss", "Baslik")
    b = make_item_id("KAP", "https://x.com/a", "baslik")
    assert a == b, "izleme parametresi ve buyuk/kucuk harf ayni haberi bolmemeli"


def test_normalize_url_strips_trackers_and_fragment():
    assert normalize_url("https://A.com/x/?utm_source=q&id=5#frag") == "https://a.com/x?id=5"


# --- TICKER CIKARIMI --------------------------------------------------

def test_extract_finds_known_ticker():
    assert extract_tickers("ESCOM bilanco acikladi", UNIVERSE) == ("ESCOM",)


def test_extract_ignores_unknown_token():
    assert extract_tickers("ZZZZZ diye bir sey yok", UNIVERSE) == ()


def test_extract_ignores_stopwords():
    out = extract_tickers("BIST 100 endeksi ve SPK karari", UNIVERSE)
    assert "BIST" not in out and "SPK" not in out


def test_extract_empty_universe_is_fail_closed():
    """Evren bossa HICBIR sey cikarilmaz -- aksi halde her buyuk harfli
    kelime ticker sanilirdi."""
    assert extract_tickers("ESCOM ARDYZ GARAN", set()) == ()


def test_extract_multiple_unique_order_preserved():
    assert extract_tickers("ESCOM ve ARDYZ, tekrar ESCOM", UNIVERSE) == ("ESCOM", "ARDYZ")


# --- RSS ADAPTORU -----------------------------------------------------

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>ESCOM yeni sozlesme imzaladi</title>
  <link>https://ornek.com/haber/1</link>
  <description>Sirket bugun aciklama yapti.</description>
  <pubDate>Mon, 22 Sep 2026 09:30:00 +0000</pubDate>
</item>
<item>
  <title>Piyasalarda genel gorunum</title>
  <link>https://ornek.com/haber/2</link>
  <description>BIST 100 gunu yukselisle kapatti.</description>
</item>
</channel></rss>"""


def test_rss_parse_produces_valid_items():
    src = RssNewsSource("ORNEK", "https://ornek.com/rss")
    res = src.parse(RSS_SAMPLE, UNIVERSE)
    assert res.ok
    assert len(res.items) == 2
    for it in res.items:
        validate(it)


def test_rss_ticker_inferred_and_marked():
    src = RssNewsSource("ORNEK", "https://ornek.com/rss")
    res = src.parse(RSS_SAMPLE, UNIVERSE)
    first = res.items[0]
    assert first.tickers == ("ESCOM",)
    assert first.match_confidence == MATCH_INFERRED


def test_rss_general_news_has_no_ticker():
    src = RssNewsSource("ORNEK", "https://ornek.com/rss")
    res = src.parse(RSS_SAMPLE, UNIVERSE)
    assert res.items[1].tickers == ()


def test_rss_missing_date_is_none_not_fabricated():
    src = RssNewsSource("ORNEK", "https://ornek.com/rss")
    res = src.parse(RSS_SAMPLE, UNIVERSE)
    assert res.items[1].published_at is None, "tarih yoksa UYDURULMAMALI"


def test_rss_item_without_link_is_rejected_not_silently_kept():
    bad = """<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Linksiz haber</title><description>x</description></item>
    </channel></rss>"""
    src = RssNewsSource("ORNEK", "https://ornek.com/rss")
    res = src.parse(bad, UNIVERSE)
    assert res.items == []
    assert res.item_count_rejected == 1, "elenen kayit SAYILMALI, sessizce kaybolmamali"


# --- KAP ADAPTORU -----------------------------------------------------

KAP_SAMPLE = json.dumps([
    {"disclosureIndex": 111, "title": "Ozel Durum Aciklamasi",
     "stockCodes": "ESCOM", "publishDate": "2026-09-22 10:15:00"},
    {"disclosureIndex": 112, "title": "Finansal Rapor",
     "stockCodes": ["ARDYZ", "GARAN"], "publishDate": "2026-09-22 11:00:00"},
])


def test_kap_parse_marks_exact_match():
    res = KapNewsSource().parse(KAP_SAMPLE, UNIVERSE)
    assert res.ok and len(res.items) == 2
    for it in res.items:
        validate(it)
        assert it.match_confidence == MATCH_EXACT
        assert it.source_kind == SOURCE_KIND_REGULATORY


def test_kap_parses_multiple_stock_codes():
    res = KapNewsSource().parse(KAP_SAMPLE, UNIVERSE)
    assert res.items[1].tickers == ("ARDYZ", "GARAN")


def test_kap_builds_url_from_disclosure_index():
    res = KapNewsSource().parse(KAP_SAMPLE, UNIVERSE)
    assert "111" in res.items[0].url


def test_kap_converts_local_time_to_utc():
    res = KapNewsSource().parse(KAP_SAMPLE, UNIVERSE)
    # 10:15 TR (UTC+3) -> 07:15 UTC
    assert res.items[0].published_at.startswith("2026-09-22T07:15")


def test_kap_unexpected_schema_fails_loudly_not_silently_empty():
    res = KapNewsSource().parse(json.dumps({"beklenmedik": "sema"}), UNIVERSE)
    assert res.ok is False
    assert "sema" in (res.error or "").lower() or "bulunamadi" in (res.error or "").lower()


def test_kap_broken_json_returns_explicit_error():
    res = KapNewsSource().parse("{bozuk json", UNIVERSE)
    assert res.ok is False and res.error


# --- STORE ------------------------------------------------------------

@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(store, "NEWS_PATH", tmp_path / "store" / "news.jsonl")
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "store" / "state.json")
    monkeypatch.setattr(store, "BASE_DIR", tmp_path)
    return tmp_path


def test_store_append_and_read_roundtrip(temp_store):
    it = _item(item_id="id1")
    assert store.append_items([it]) == 1
    back = store.read_all()
    assert len(back) == 1 and back[0].item_id == "id1"


def test_store_is_idempotent(temp_store):
    it = _item(item_id="id1")
    assert store.append_items([it]) == 1
    assert store.append_items([it]) == 0, "ayni kayit ikinci kez YAZILMAMALI"
    assert len(store.read_all()) == 1


def test_store_raw_never_overwritten(temp_store):
    p1 = store.save_raw("SRC", "birinci", "run1")
    p2 = store.save_raw("SRC", "ikinci", "run1")
    assert p1 != p2, "ham yanit ASLA uzerine yazilmamali"
    assert (temp_store / p1).read_text(encoding="utf-8") == "birinci"


def test_store_state_write_is_atomic_and_roundtrips(temp_store):
    store.save_state({"sources": {"KAP": {"last_success_at": "x"}}})
    assert store.read_state()["sources"]["KAP"]["last_success_at"] == "x"


def test_store_corrupt_line_does_not_break_read(temp_store):
    store.append_items([_item(item_id="ok1")])
    with store.NEWS_PATH.open("a", encoding="utf-8") as f:
        f.write("{bozuk satir\n")
    store.append_items([_item(item_id="ok2")])
    assert len(store.read_all()) == 2, "bozuk satir okumayi durdurmamali"


# --- HEALTH -----------------------------------------------------------

def _now():
    return datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def test_health_all_fresh_is_healthy():
    recent = (_now() - timedelta(minutes=2)).isoformat()
    state = {"sources": {"KAP": {"last_success_at": recent}, "RSS": {"last_success_at": recent}}}
    h = health_mod.overall_health(state, now=_now())
    assert h["freshness"] == health_mod.HEALTHY
    assert h["completeness"] == health_mod.HEALTHY
    assert h["status"] == health_mod.HEALTHY


def test_health_fresh_but_incomplete_is_distinguished():
    """KRITIK ayrim: veri TAZE ama kaynaklarin bir kismi coktu."""
    recent = (_now() - timedelta(minutes=2)).isoformat()
    state = {"sources": {
        "KAP": {"last_success_at": recent},
        "RSS": {"last_error": "HTTP 500"},   # hic basarili cekim yok
    }}
    h = health_mod.overall_health(state, now=_now())
    assert h["freshness"] == health_mod.HEALTHY, "en az bir kaynak taze"
    assert h["completeness"] == health_mod.DEGRADED, "ama butunluk bozuk"
    assert h["status"] == health_mod.DEGRADED


def test_health_complete_but_stale_is_distinguished():
    """Tersi durum: tum kaynaklar calisiyor ama veri bayat."""
    old = (_now() - timedelta(hours=3)).isoformat()
    state = {"sources": {"KAP": {"last_success_at": old}, "RSS": {"last_success_at": old}}}
    h = health_mod.overall_health(state, now=_now())
    assert h["freshness"] == health_mod.DEGRADED
    assert h["status"] == health_mod.DEGRADED


def test_health_no_state_is_unhealthy_not_silently_ok():
    h = health_mod.overall_health({}, now=_now())
    assert h["status"] == health_mod.UNHEALTHY


# --- MIMARI GARANTILER ------------------------------------------------

def test_api_module_never_imports_network_library():
    """KRITIK (PULSE ilkesi): read-only API ag kutuphanesi IMPORT BILE
    ETMEMELI. Bu, 'API kazara aga cikar' sinifindaki hatalari yapisal
    olarak imkansiz kilar."""
    import ast
    src = Path(__file__).resolve().parent.parent / "haber" / "api.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    banned = {"requests", "httpx", "urllib", "aiohttp", "feedparser", "socket"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned, f"yasak import: {a.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert node.module.split(".")[0] not in banned, f"yasak import: {node.module}"


def test_contract_has_no_signal_or_recommendation_field():
    """NEWS != SIGNAL. Contract'ta yon/skor/tavsiye alani OLMAMALI --
    aksi halde haber katmani sessizce bir strateji katmanina donusur."""
    banned = {"direction", "signal", "score", "recommendation", "action",
              "sentiment", "target_price", "rating", "buy", "sell"}
    fields = set(NewsItem.__dataclass_fields__.keys())
    assert not (fields & banned), f"contract'ta yasak alan: {fields & banned}"


# --- IZLEME LISTELERI -------------------------------------------------

@pytest.fixture
def temp_wl(tmp_path, monkeypatch):
    from haber import watchlists as wl
    monkeypatch.setattr(wl, "WATCHLISTS_PATH", tmp_path / "watchlists.json")
    return wl


def test_watchlist_upsert_and_load(temp_wl):
    temp_wl.upsert("BOLT", ["escom", "ardyz"], universe=UNIVERSE)
    assert temp_wl.get_tickers("BOLT") == ["ESCOM", "ARDYZ"], "buyuk harfe cevrilmeli"


def test_watchlist_dedupes_preserving_order(temp_wl):
    temp_wl.upsert("X", ["ESCOM", "ARDYZ", "ESCOM"], universe=UNIVERSE)
    assert temp_wl.get_tickers("X") == ["ESCOM", "ARDYZ"]


def test_watchlist_rejects_ticker_outside_universe(temp_wl):
    """Yazim hatasiyla HICBIR ZAMAN eslesmeyecek liste olusturmayi onler."""
    with pytest.raises(temp_wl.WatchlistError):
        temp_wl.upsert("X", ["ESCOM", "YANLISKOD"], universe=UNIVERSE)


def test_watchlist_allows_any_ticker_when_universe_absent(temp_wl):
    """Evren dosyasi yoksa arac yine de kullanilabilmeli."""
    temp_wl.upsert("X", ["ESCOM", "ZZZZZ"], universe=None)
    assert temp_wl.get_tickers("X") == ["ESCOM", "ZZZZZ"]


def test_watchlist_rejects_bad_name(temp_wl):
    with pytest.raises(temp_wl.WatchlistError):
        temp_wl.upsert("", ["ESCOM"], universe=UNIVERSE)
    with pytest.raises(temp_wl.WatchlistError):
        temp_wl.upsert("kotu/isim", ["ESCOM"], universe=UNIVERSE)


def test_watchlist_rejects_bad_ticker_format(temp_wl):
    with pytest.raises(temp_wl.WatchlistError):
        temp_wl.upsert("X", ["es-com"], universe=None)


def test_watchlist_delete(temp_wl):
    temp_wl.upsert("X", ["ESCOM"], universe=UNIVERSE)
    temp_wl.delete("X")
    assert temp_wl.load_all() == {}


def test_watchlist_multiple_lists_coexist(temp_wl):
    temp_wl.upsert("BOLT", ["ESCOM"], universe=UNIVERSE)
    temp_wl.upsert("AEGIS", ["GARAN", "AKBNK"], universe=UNIVERSE)
    allw = temp_wl.load_all()
    assert set(allw) == {"BOLT", "AEGIS"}
    assert allw["AEGIS"] == ["GARAN", "AKBNK"]


def test_watchlist_save_is_atomic_roundtrip(temp_wl):
    temp_wl.upsert("X", ["ESCOM"], universe=UNIVERSE)
    assert temp_wl.WATCHLISTS_PATH.exists()
    assert json.loads(temp_wl.WATCHLISTS_PATH.read_text(encoding="utf-8"))["X"] == ["ESCOM"]


def test_api_writes_only_to_watchlists_never_to_news_store():
    """KRITIK MIMARI GARANTI: API izleme listesi yazabilir ama toplanan
    veri deposuna (news.jsonl / raw) ASLA yazmaz -- 'collector veri
    deposunun tek sahibidir' kuralı korunur."""
    import ast
    src = Path(__file__).resolve().parent.parent / "haber" / "api.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    banned_calls = {"append_items", "save_raw", "save_state"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            assert name not in banned_calls, f"API veri deposuna yaziyor: {name}"


# =====================================================================
# INSPECTION BULGULARI -- yedi duzeltmenin regresyon testleri
# =====================================================================

# --- 1) RSS: HTTP 200 ama govde RSS DEGIL ----------------------------

def test_rss_html_body_is_not_silently_empty_feed():
    """KRITIK: yayinci hata sayfasi/Cloudflare HTML donerse, bu
    'basarili bos akis' SAYILMAMALI."""
    html = "<!DOCTYPE html><html><body><h1>404 Not Found</h1></body></html>"
    res = RssNewsSource("ORNEK", "x").parse(html, UNIVERSE)
    assert res.ok is False
    assert res.feed_status == "UNPARSEABLE"
    assert "RSS DEGIL" in (res.error or "")


def test_rss_garbage_body_is_rejected():
    res = RssNewsSource("ORNEK", "x").parse("bu tamamen sacma bir govde", UNIVERSE)
    assert res.ok is False
    assert res.feed_status in ("UNPARSEABLE", "EMPTY_SUSPECT")


def test_rss_genuinely_empty_but_valid_feed_is_accepted():
    """Gecerli ama gercekten bos akis MESRU -- hata sayilmamali."""
    empty = """<?xml version="1.0"?><rss version="2.0"><channel>
    <title>Bos Akis</title><link>https://ornek.com</link>
    </channel></rss>"""
    res = RssNewsSource("ORNEK", "x").parse(empty, UNIVERSE)
    assert res.ok is True
    assert res.feed_status == "EXPECTED_EMPTY"
    assert res.items == []


def test_rss_valid_nonempty_marked_correctly():
    res = RssNewsSource("ORNEK", "x").parse(RSS_SAMPLE, UNIVERSE)
    assert res.feed_status == "VALID_NONEMPTY"


# --- 2) Basarisiz yanitin raw'i KORUNUR -------------------------------

def test_failed_response_raw_is_preserved(temp_store, monkeypatch):
    """PULSE dersi: raw ONCE korunur, validation SONRA. Hata anindaki
    kanit atilmamali."""
    from haber import collector as coll
    from haber.sources.base import FetchResult

    class FailingSource:
        source_id = "COKEN"
        source_kind = "MEDIA"
        def fetch(self, universe):
            return FetchResult(source_id="COKEN", ok=False, http_status=500,
                               raw_text="<html>sunucu hatasi govdesi</html>",
                               items=[], error="HTTP 500")

    monkeypatch.setattr(coll, "build_sources", lambda: [FailingSource()])
    monkeypatch.setattr(coll, "load_universe", lambda: UNIVERSE)
    out = coll.collect_once(verbose=False)

    raw_files = list((temp_store / "raw").glob("*.raw"))
    assert raw_files, "basarisiz yanitin ham govdesi KAYBOLMAMALI"
    assert any("FAILED" in p.name for p in raw_files), "hatali raw ayirt edilebilir olmali"
    assert "sunucu hatasi govdesi" in raw_files[0].read_text(encoding="utf-8")
    assert out["results"][0]["raw_ref"], "sonucta raw referansi bildirilmeli"


# --- 3) Provenance zinciri: raw_ref habere baglaniyor -----------------

def test_successful_items_carry_raw_ref_back_to_source_payload(temp_store, monkeypatch):
    """news.jsonl'deki bir kayittan, onu ureten ham dosyaya
    gidilebilmeli."""
    from haber import collector as coll
    from haber.sources.base import FetchResult, FEED_VALID_NONEMPTY

    item = _item(item_id="prov1", raw_ref=None)

    class OkSource:
        source_id = "IYI"
        source_kind = "MEDIA"
        def fetch(self, universe):
            return FetchResult(source_id="IYI", ok=True, http_status=200,
                               raw_text="<rss>govde</rss>", items=[item],
                               feed_status=FEED_VALID_NONEMPTY, elapsed_seconds=0.1)

    monkeypatch.setattr(coll, "build_sources", lambda: [OkSource()])
    monkeypatch.setattr(coll, "load_universe", lambda: UNIVERSE)
    coll.collect_once(verbose=False)

    saved = store.read_all()
    assert len(saved) == 1
    ref = saved[0].raw_ref
    assert ref, "kaydin raw_ref'i DOLU olmali (provenance zinciri)"
    assert (temp_store / ref).exists(), "raw_ref gercek bir dosyayi isaret etmeli"
    assert (temp_store / ref).read_text(encoding="utf-8") == "<rss>govde</rss>"


# --- 4) Single-instance lock ------------------------------------------

def test_lock_blocks_second_instance(tmp_path):
    from haber.lock import CollectorAlreadyRunning, SingleInstanceLock
    p = tmp_path / "c.lock"
    first = SingleInstanceLock(path=p).acquire()
    try:
        with pytest.raises(CollectorAlreadyRunning):
            SingleInstanceLock(path=p).acquire()
    finally:
        first.release()


def test_lock_released_allows_next_instance(tmp_path):
    from haber.lock import SingleInstanceLock
    p = tmp_path / "c.lock"
    with SingleInstanceLock(path=p):
        pass
    second = SingleInstanceLock(path=p).acquire()   # artik serbest
    second.release()
    assert not p.exists()


def test_stale_lock_is_taken_over(tmp_path):
    """Surec cokerse kilit dosyasi kalir -- arac KALICI olarak
    kilitlenmemeli."""
    import os, time as _t
    from haber.lock import SingleInstanceLock
    p = tmp_path / "c.lock"
    p.write_text('{"pid": 999999}', encoding="utf-8")
    old = _t.time() - 10_000
    os.utime(p, (old, old))

    lk = SingleInstanceLock(path=p, stale_after=60).acquire()  # bayat -> devral
    assert lk.acquired
    lk.release()


def test_fresh_lock_is_not_taken_over(tmp_path):
    from haber.lock import CollectorAlreadyRunning, SingleInstanceLock
    p = tmp_path / "c.lock"
    p.write_text('{"pid": 999999}', encoding="utf-8")
    with pytest.raises(CollectorAlreadyRunning):
        SingleInstanceLock(path=p, stale_after=10_000).acquire()


# --- 5) Mimari: ag cagrilarinin YERI ----------------------------------

def test_only_source_adapters_may_import_network_libraries():
    """'collector.py ag'a cikan tek dosya' ifadesi LITERAL olarak
    yanlisti -- ag cagrilari sources/ altinda. Dogru kural: ag
    kutuphanesini SADECE haber/sources/* import edebilir. Bu testle
    kural artik slogan degil, YAPISAL bir garanti."""
    import ast
    root = Path(__file__).resolve().parent.parent / "haber"
    net = {"requests", "httpx", "urllib", "aiohttp", "socket", "feedparser"}

    offenders = []
    for py in root.rglob("*.py"):
        rel = py.relative_to(root)
        allowed = rel.parts[0] == "sources"
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in net and not allowed:
                    offenders.append(f"{rel} -> {m}")
    assert not offenders, f"ag kutuphanesi yanlis katmanda: {offenders}"


def test_requirements_file_exists_and_is_pinned():
    """Sunucuya tasimadan once bagimliliklar SABITLENMIS olmali."""
    req = Path(__file__).resolve().parent.parent / "requirements.txt"
    assert req.exists(), "requirements.txt yok"
    lines = [l.strip() for l in req.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    assert lines, "requirements.txt bos"
    for l in lines:
        assert "==" in l, f"surum sabitlenmemis: {l}"


# --- RETENTION (7 gunluk saklama penceresi) ---------------------------

def _aged_item(item_id, days_ago, now):
    from datetime import timedelta as _td
    return _item(item_id=item_id,
                 collected_at=(now - _td(days=days_ago)).isoformat())


def test_retention_deletes_old_news_keeps_recent(temp_store):
    from haber import retention
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    store.append_items([_aged_item("yeni", 2, now), _aged_item("eski", 10, now)])

    stats = retention.prune_news(days=7, now=now)
    ids = {i.item_id for i in store.read_all()}
    assert ids == {"yeni"}
    assert stats["deleted"] == 1 and stats["kept"] == 1


def test_retention_boundary_keeps_item_just_inside_window(temp_store):
    from haber import retention
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    store.append_items([_aged_item("sinirda", 6, now)])
    retention.prune_news(days=7, now=now)
    assert len(store.read_all()) == 1, "6 gunluk kayit 7 gunluk pencerede KALMALI"


def test_retention_keeps_item_with_unreadable_timestamp(temp_store):
    """Zaman damgasi okunamayan kayit SILINMEZ -- silmek geri alinamaz,
    saklamak zararsizdir."""
    from haber import retention
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    store.append_items([_item(item_id="bozukts", collected_at="tarih-degil")])
    retention.prune_news(days=7, now=now)
    assert len(store.read_all()) == 1


def test_retention_deletes_old_raw_files(temp_store):
    from haber import retention
    import os as _os, time as _t
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

    eski = store.save_raw("SRC", "eski govde", "r1")
    yeni = store.save_raw("SRC", "yeni govde", "r2")
    old_epoch = (now - timedelta(days=30)).timestamp()
    _os.utime(temp_store / eski, (old_epoch, old_epoch))
    new_epoch = (now - timedelta(days=1)).timestamp()
    _os.utime(temp_store / yeni, (new_epoch, new_epoch))

    stats = retention.prune_raw(days=7, now=now)
    assert stats["deleted"] == 1 and stats["kept"] == 1
    assert not (temp_store / eski).exists()
    assert (temp_store / yeni).exists()


def test_retention_prunes_news_and_raw_together_keeping_provenance_consistent(temp_store):
    """KRITIK TUTARLILIK: raw silinip haber kaydi kalirsa raw_ref bosa
    isaret ederdi. Ikisi AYNI pencereyle budanmali."""
    from haber import retention
    import os as _os
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

    old_raw = store.save_raw("SRC", "eski", "r1")
    _os.utime(temp_store / old_raw,
              ((now - timedelta(days=30)).timestamp(),) * 2)
    store.append_items([
        _item(item_id="eski", collected_at=(now - timedelta(days=30)).isoformat(),
              raw_ref=old_raw),
    ])

    retention.prune_all(days=7, now=now)

    for it in store.read_all():
        if it.raw_ref:
            assert (temp_store / it.raw_ref).exists(), \
                "kalan her kaydin raw dosyasi da KALMALI"


def test_collector_prunes_after_collecting_not_before(temp_store, monkeypatch):
    """Once topla, SONRA buda -- tersi olsaydi ayni turda gelen yeni bir
    kayit silinebilirdi."""
    from haber import collector as coll
    from haber.sources.base import FetchResult, FEED_VALID_NONEMPTY

    fresh = _item(item_id="taze", collected_at=utc_now_iso())

    class OkSource:
        source_id = "S"; source_kind = "MEDIA"
        def fetch(self, universe):
            return FetchResult(source_id="S", ok=True, http_status=200,
                               raw_text="govde", items=[fresh],
                               feed_status=FEED_VALID_NONEMPTY, elapsed_seconds=0.1)

    monkeypatch.setattr(coll, "build_sources", lambda: [OkSource()])
    monkeypatch.setattr(coll, "load_universe", lambda: UNIVERSE)
    out = coll.collect_once(verbose=False, retention_days=7)

    assert out["prune"] is not None
    assert len(store.read_all()) == 1, "yeni toplanan kayit budanmamali"


def test_collector_can_skip_pruning(temp_store, monkeypatch):
    from haber import collector as coll
    from haber.sources.base import FetchResult, FEED_VALID_NONEMPTY

    class OkSource:
        source_id = "S"; source_kind = "MEDIA"
        def fetch(self, universe):
            return FetchResult(source_id="S", ok=True, http_status=200,
                               raw_text="g", items=[], feed_status=FEED_VALID_NONEMPTY)

    monkeypatch.setattr(coll, "build_sources", lambda: [OkSource()])
    monkeypatch.setattr(coll, "load_universe", lambda: UNIVERSE)
    out = coll.collect_once(verbose=False, retention_days=None)
    assert out["prune"] is None


def test_default_retention_is_seven_days():
    from haber.retention import DEFAULT_RETENTION_DAYS
    assert DEFAULT_RETENTION_DAYS == 7


# --- KAP gercek uc nokta sozlesmesi ------------------------------------

def test_kap_uses_post_with_required_referer_and_body():
    """KAP WAF'i Referer header'ini kontrol ediyor; uc nokta POST ve
    govde fromDate/toDate/mkkMemberOidList/subjectList bekliyor."""
    from unittest.mock import MagicMock, patch
    from haber.sources.kap import KAP_REFERER, DEFAULT_ENDPOINT

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, body=json, headers=headers)
        r = MagicMock(); r.status_code = 200
        r.text = "[]"; r.content = b"[]"
        return r

    with patch("haber.sources.kap.requests.post", side_effect=fake_post):
        KapNewsSource().fetch(UNIVERSE)

    assert captured["url"] == DEFAULT_ENDPOINT
    assert captured["headers"]["Referer"] == KAP_REFERER
    assert set(captured["body"]) == {"fromDate", "toDate", "mkkMemberOidList", "subjectList"}
    assert captured["body"]["mkkMemberOidList"] == []


def test_kap_parses_real_field_names():
    """Gercek KAP alan adlari: subject / companyName / stockCodes /
    disclosureIndex / publishDate."""
    sample = json.dumps([{
        "disclosureIndex": 1610843, "subject": "Sermaye Artirimi",
        "companyName": "ESCOM BILISIM", "stockCodes": "ESCOM",
        "publishDate": "2026-09-25 14:05:00",
    }])
    res = KapNewsSource().parse(sample, UNIVERSE)
    assert res.ok and len(res.items) == 1
    it = res.items[0]
    assert it.tickers == ("ESCOM",)
    assert it.match_confidence == MATCH_EXACT
    assert "1610843" in it.url
    assert "ESCOM BILISIM" in it.title and "Sermaye Artirimi" in it.title
    assert it.published_at.startswith("2026-09-25T11:05")  # TR -> UTC


# =====================================================================
# KAP konu siniflandirmasi / alias eslemesi / KURULU hatasi
# =====================================================================

def test_kap_stock_codes_validated_against_universe():
    """GERCEK HATA REGRESYONU: SPK bulteni gibi sirkete bagli olmayan
    bildirimlerde baslik metninden 'KURULU' gibi sembol-gorunumlu
    kelimeler cikiyordu."""
    from haber.sources.kap import _parse_stock_codes
    assert _parse_stock_codes("SERMAYE PIYASASI KURULU", UNIVERSE) == ()
    assert _parse_stock_codes("ESCOM, ARDYZ", UNIVERSE) == ("ESCOM", "ARDYZ")


def test_kap_stock_codes_accepts_all_when_universe_absent():
    from haber.sources.kap import _parse_stock_codes
    assert _parse_stock_codes("ESCOM", None) == ("ESCOM",)


def test_kap_title_field_is_not_used_as_stock_code_source():
    """kapTitle bir BASLIK alanidir; sembol kaynagi olarak KULLANILMAMALI."""
    import inspect
    from haber.sources import kap as kap_mod
    src = inspect.getsource(kap_mod)
    assert '"kapTitle"' not in src


def test_kap_subject_classification():
    from haber.kap_subjects import classify_subject
    assert classify_subject("Pay Bazında Devre Kesici Bildirimi") == "ROUTINE"
    assert classify_subject("Piyasa Yapıcılığı") == "ROUTINE"
    assert classify_subject("Kar Payı Dağıtım İşlemlerine İlişkin Bildirim") == "MATERIAL"
    assert classify_subject("Yeni İş İlişkisi") == "MATERIAL"
    assert classify_subject("İhale Süreci / Sonucu") == "MATERIAL"
    assert classify_subject("Özel Durum Açıklaması") == "MATERIAL"


def test_turkish_dotted_i_normalization_regression():
    """GERCEK HATA REGRESYONU: Python'da 'İ'.lower() iki karakter uretir
    (i + birlesen nokta); bu yuzden 'İhale' kalibi eslesmiyordu."""
    from haber.kap_subjects import _norm
    assert _norm("İhale") == "ihale"
    assert "\u0307" not in _norm("İŞ İLİŞKİSİ")


def test_material_beats_routine_when_both_match():
    from haber.kap_subjects import classify_subject
    # "genel kurul" (MATERIAL) + "bulten" (ROUTINE) ayni baslikta
    assert classify_subject("Genel Kurul Bülteni") == "MATERIAL"


def test_company_alias_catches_news_without_ticker_code():
    """Haber metninde sembol yoksa sirket adindan eslesmeli."""
    from haber.tickers import extract_tickers, extract_tickers_with_aliases
    aliases = {"garanti bankasi": "GARAN"}
    uni = {"GARAN"}
    text = "Garanti Bankası 3. çeyrek kârını açıkladı"
    assert extract_tickers(text, uni) == (), "sembol tabanli cikarim bunu kacirir"
    assert extract_tickers_with_aliases(text, uni, aliases) == ("GARAN",)


def test_company_alias_respects_universe():
    from haber.tickers import extract_tickers_with_aliases
    aliases = {"garanti bankasi": "GARAN"}
    assert extract_tickers_with_aliases("Garanti Bankası", set(), aliases) == ()
    assert extract_tickers_with_aliases("Garanti Bankası", {"THYAO"}, aliases) == ()


def test_company_alias_does_not_duplicate_existing_ticker():
    from haber.tickers import extract_tickers_with_aliases
    aliases = {"garanti bankasi": "GARAN"}
    out = extract_tickers_with_aliases("GARAN Garanti Bankası", {"GARAN"}, aliases)
    assert out == ("GARAN",)


def test_company_alias_file_is_valid_and_maps_to_known_codes():
    from haber.tickers import load_company_aliases
    aliases = load_company_aliases()
    assert len(aliases) > 50
    for name, ticker in aliases.items():
        assert re.fullmatch(r"[A-Z0-9]{3,6}", ticker), f"gecersiz kod: {name} -> {ticker}"
        assert not name.startswith("_")


def test_alias_matching_stays_inferred_not_exact():
    """Alias eslesmesi bir CIKARIMDIR -- EXACT olarak isaretlenmemeli."""
    rss = """<?xml version="1.0"?><rss version="2.0"><channel>
    <title>T</title><link>https://o.com</link>
    <item><title>Garanti Bankası kârını açıkladı</title>
    <link>https://o.com/1</link><description>x</description></item>
    </channel></rss>"""
    res = RssNewsSource("ORNEK", "x").parse(rss, {"GARAN"})
    assert res.items[0].match_confidence == MATCH_INFERRED


# --- PWA (uygulama olarak yukleme) ------------------------------------

def test_manifest_is_valid_and_complete():
    root = Path(__file__).resolve().parents[1]
    m = json.loads((root / "web" / "manifest.json").read_text(encoding="utf-8"))
    assert m["display"] == "standalone"
    assert m["start_url"] == "/"
    assert m["scope"] == "/"
    assert len(m["icons"]) >= 2
    assert any(i.get("purpose") == "maskable" for i in m["icons"]), \
        "maskable ikon olmadan Android'de ikon kirpilir"


def test_manifest_icon_files_actually_exist():
    root = Path(__file__).resolve().parents[1]
    m = json.loads((root / "web" / "manifest.json").read_text(encoding="utf-8"))
    for icon in m["icons"]:
        rel = icon["src"].replace("/static/", "web/")
        assert (root / rel).exists(), f"manifest'te var, diskte yok: {icon['src']}"


def test_service_worker_does_not_cache_anything():
    """KRITIK: bu bir haber araci -- onbellek BAYAT HABER demek.
    Service worker SADECE yuklenebilirlik icin var, fetch handler
    EKLENMEMELI."""
    root = Path(__file__).resolve().parents[1]
    sw = (root / "web" / "sw.js").read_text(encoding="utf-8")
    assert "caches.open" not in sw
    assert "cache.put" not in sw
    assert 'addEventListener("fetch"' not in sw
    assert "addEventListener('fetch'" not in sw


def test_api_serves_manifest_and_sw_at_root_scope():
    """sw.js KOK kapsamda sunulmali; /static/sw.js olsa kapsam
    /static/ ile sinirli kalir ve yukleme calismaz."""
    import ast
    src = (Path(__file__).resolve().parents[1] / "haber" / "api.py").read_text(encoding="utf-8")
    assert '@app.get("/sw.js")' in src
    assert '@app.get("/manifest.json")' in src


def test_index_registers_service_worker_and_links_manifest():
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in html
    assert 'serviceWorker' in html
    assert 'apple-touch-icon' in html


def test_startup_batch_files_are_ascii_only():
    """Windows cmd varsayilan kod sayfasinda Turkce karakterler bozuk
    gorunur -- .bat dosyalari salt ASCII olmali."""
    root = Path(__file__).resolve().parents[1]
    for name in ("basla.bat", "basla_agda.bat"):
        p = root / name
        assert p.exists(), f"{name} yok"
        p.read_bytes().decode("ascii")  # ASCII degilse exception


def test_startup_batch_starts_both_processes():
    root = Path(__file__).resolve().parents[1]
    txt = (root / "basla.bat").read_text(encoding="ascii")
    assert "haber.collector" in txt
    assert "uvicorn haber.api:app" in txt
    assert "127.0.0.1" in txt


def test_lan_batch_binds_all_interfaces_and_warns_about_firewall():
    root = Path(__file__).resolve().parents[1]
    txt = (root / "basla_agda.bat").read_text(encoding="ascii")
    assert "0.0.0.0" in txt
    assert "ipconfig" in txt
    assert "Duvari" in txt or "duvari" in txt.lower()
