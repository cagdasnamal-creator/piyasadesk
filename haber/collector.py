"""
COLLECTOR -- agin cikan TEK bilesen.

PULSE mimarisiyle birebir:
  - Collector = writer, ag erisimi SADECE burada
  - API/UI = read-only consumer, ag erisimi YOK
  - Fail-soft: bir kaynak coktugunde digerleri DURMAZ (PULSE'un
    "Data Defect Containment Principle" karsiligi)
  - Her denemenin sonucu ACIKCA kaydedilir -- sessiz bos donus yok

CLI:
    python -m haber.collector            # bir kez topla
    python -m haber.collector --loop 300 # her 300 saniyede bir topla
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone

from haber import retention, store
from haber.config import build_sources
from haber.lock import CollectorAlreadyRunning, SingleInstanceLock
from haber.retention import DEFAULT_RETENTION_DAYS
from haber.contract import utc_now_iso
from haber.tickers import load_universe


def collect_once(verbose: bool = True,
                 retention_days: int | None = DEFAULT_RETENTION_DAYS) -> dict:
    """Tum kaynaklari bir kez toplar. HICBIR kaynak digerini durdurmaz.

    retention_days: toplama bittikten SONRA bu pencereden eski veriler
    budanir. None verilirse budama yapilmaz."""
    run_id = uuid.uuid4().hex[:10]
    universe = load_universe()
    sources = build_sources()
    state = store.read_state()
    state.setdefault("sources", {})
    known_ids = store.read_existing_ids()

    if verbose:
        print(f"[COLLECTOR] run_id={run_id} kaynak={len(sources)} evren={len(universe)} sembol")
        if not universe:
            print("[UYARI] Sembol evreni BOS -- RSS kaynaklarinda ticker cikarimi "
                  "YAPILMAYACAK (fail-closed). data/universe.txt olusturun.")

    total_new = 0
    results = []

    for src in sources:
        attempt_at = utc_now_iso()
        try:
            result = src.fetch(universe)
        except Exception as e:  # adaptor icinde beklenmeyen hata -> kampanya DURMAZ
            result = None
            error = f"{type(e).__name__}: {e}"
            if verbose:
                print(f"  [{src.source_id}] BEKLENMEYEN HATA -- {error}")
            st = state["sources"].setdefault(src.source_id, {})
            st.update({"last_attempt_at": attempt_at, "last_error": error})
            results.append({"source_id": src.source_id, "ok": False, "error": error, "new_items": 0})
            continue

        st = state["sources"].setdefault(src.source_id, {})
        st["last_attempt_at"] = attempt_at

        # ---------------------------------------------------------------
        # RAW ONCE KORUNUR, VALIDATION SONRA.
        # PULSE dersi: en cok ihtiyac duyulan kanit, tam hata anindaki
        # kanittir. Eskiden basarisiz yanitlarda save_raw'a hic
        # ulasilmiyordu -- yani HTTP 500 veya "bu RSS degil, HTML"
        # durumunda elimizde inceleyecek HICBIR SEY kalmiyordu.
        # Artik govde ne olursa olsun once diske yazilir.
        # ---------------------------------------------------------------
        raw_ref = None
        if result.raw_text is not None:
            raw_ref = store.save_raw(src.source_id, result.raw_text, run_id,
                                      failed=not result.ok)
            st["last_raw_ref"] = raw_ref

        if not result.ok:
            st["last_error"] = result.error
            st["last_feed_status"] = result.feed_status
            if verbose:
                extra = f" [raw: {raw_ref}]" if raw_ref else " [govde yok]"
                print(f"  [{src.source_id}] HATA -- {result.error}{extra}")
            results.append({"source_id": src.source_id, "ok": False,
                            "error": result.error, "new_items": 0,
                            "raw_ref": raw_ref})
            continue

        # Provenance zincirini tamamla: her kayit, hangi ham dosyadan
        # uretildigini TASIR. (NewsItem frozen oldugu icin replace ile.)
        items = [replace(it, raw_ref=raw_ref) for it in result.items] if raw_ref else result.items

        new_count = store.append_items(items, known_ids)
        total_new += new_count

        st.update({
            "last_success_at": utc_now_iso(),
            "last_error": None,
            "last_feed_status": result.feed_status,
            "last_item_count": len(items),
            "last_new_item_count": new_count,
            "last_rejected_count": result.item_count_rejected,
            "last_elapsed_seconds": round(result.elapsed_seconds or 0, 3),
        })
        if verbose:
            print(f"  [{src.source_id}] OK -- {len(items)} kayit "
                  f"({new_count} yeni, {result.item_count_rejected} contract-red) "
                  f"[{result.feed_status}] {result.elapsed_seconds:.2f}s")
        results.append({"source_id": src.source_id, "ok": True,
                        "items": len(items), "new_items": new_count,
                        "raw_ref": raw_ref})

    state["last_run_id"] = run_id
    state["last_run_at"] = utc_now_iso()

    # --- Retention: toplama BITTIKTEN sonra buda ---
    # Once toplayip sonra budamak onemli: tersi olsaydi, yeni gelen ama
    # eski tarihli bir kayit ayni turda silinebilirdi.
    prune_stats = None
    if retention_days is not None:
        prune_stats = retention.prune_all(retention_days)
        state["last_prune"] = {"at": utc_now_iso(), **prune_stats}
        if verbose and (prune_stats["news"]["deleted"] or prune_stats["raw"]["deleted"]):
            mb = prune_stats["raw"]["freed_bytes"] / (1024 * 1024)
            print(f"[RETENTION] {retention_days} gunden eski: "
                  f"{prune_stats['news']['deleted']} kayit, "
                  f"{prune_stats['raw']['deleted']} ham dosya silindi "
                  f"({mb:.1f} MB)")

    store.save_state(state)

    if verbose:
        print(f"[COLLECTOR] tamamlandi -- {total_new} yeni kayit")

    return {"run_id": run_id, "total_new": total_new, "results": results,
            "prune": prune_stats}


def main() -> int:
    parser = argparse.ArgumentParser(description="Hisse Haber Merkezi -- collector")
    parser.add_argument("--loop", type=int, default=0,
                        help="saniye cinsinden dongu araligi (0 = tek sefer)")
    parser.add_argument("--no-lock", action="store_true",
                        help="tek-instance kilidini atla (ONERILMEZ)")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS,
                        help=f"kac gunluk veri saklansin (varsayilan {DEFAULT_RETENTION_DAYS})")
    parser.add_argument("--no-prune", action="store_true",
                        help="bu calistirmada budama yapma")
    args = parser.parse_args()

    # Tek-instance kilidi: Task Scheduler'da bir calistirma uzun surerse
    # bir sonraki tetikleme uzerine binebilir. Iki collector es zamanli
    # calisirsa ayni haber iki kez yazilabilir ve state dosyasi
    # birbirinin uzerine yazilir.
    lock = None
    if not args.no_lock:
        try:
            lock = SingleInstanceLock().acquire()
        except CollectorAlreadyRunning as e:
            print(f"[KILIT] {e}")
            return 3  # ozel cikis kodu -- zamanlayici ayirt edebilsin

    keep = None if args.no_prune else args.retention_days

    try:
        if args.loop <= 0:
            collect_once(retention_days=keep)
            return 0

        print(f"[COLLECTOR] dongu modu -- her {args.loop} saniyede bir. "
              f"Durdurmak icin Ctrl+C.")
        try:
            while True:
                collect_once(retention_days=keep)
                if lock:
                    lock.touch()  # uzun dongulerde kilit bayat sayilmasin
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\n[COLLECTOR] durduruldu.")
        return 0
    finally:
        if lock:
            lock.release()


if __name__ == "__main__":
    sys.exit(main())
