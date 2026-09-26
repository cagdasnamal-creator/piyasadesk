"""
COLLECTOR_HEALTH -- PULSE'un saglik modelinin birebir karsiligi.

En kritik ayrim (PULSE'tan devralinan ders):
    FRESHNESS != COMPLETENESS

  - FRESH ama EKSIK: kaynak 2 dakika once basariyla cekildi, ama 5
    kaynaktan 2'si hata verdi -> veri TAZE fakat EKSIK.
  - STALE ama TAM: tum kaynaklar basarili, ama en son 3 saat once
    cekildi -> veri TAM fakat BAYAT.

Bu ikisi ayri ayri raporlanir; UI ikisini de gosterir. "Yesil nokta"
tek basina yeterli degildir.

Durumlar: HEALTHY / DEGRADED / UNHEALTHY
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNHEALTHY = "UNHEALTHY"

# Kaynak bu sureden uzun zamandir basariyla cekilmediyse "bayat"
DEFAULT_STALE_AFTER_MINUTES = 30


def _parse_iso(value: str | None):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def source_health(source_state: dict, now: datetime | None = None,
                  stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES) -> dict:
    """Tek bir kaynagin saglik durumu."""
    now = now or datetime.now(timezone.utc)
    last_ok = _parse_iso(source_state.get("last_success_at"))
    last_error = source_state.get("last_error")

    age_minutes = None
    if last_ok:
        age_minutes = (now - last_ok).total_seconds() / 60.0

    if last_ok is None:
        status = UNHEALTHY
        reason = "hic basarili cekim yok"
    elif age_minutes is not None and age_minutes > stale_after_minutes:
        status = DEGRADED
        reason = f"son basarili cekim {age_minutes:.0f} dk once (esik {stale_after_minutes} dk)"
    elif last_error:
        status = DEGRADED
        reason = "son denemede hata var (onceki veri hala taze)"
    else:
        status = HEALTHY
        reason = "guncel"

    return {
        "status": status,
        "reason": reason,
        "last_success_at": source_state.get("last_success_at"),
        "last_attempt_at": source_state.get("last_attempt_at"),
        "last_error": last_error,
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "last_item_count": source_state.get("last_item_count"),
    }


def overall_health(state: dict, now: datetime | None = None,
                   stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES) -> dict:
    """Tum kaynaklarin birlesik durumu -- freshness ve completeness AYRI
    raporlanir."""
    sources = state.get("sources", {})
    if not sources:
        return {
            "status": UNHEALTHY,
            "freshness": UNHEALTHY,
            "completeness": UNHEALTHY,
            "reason": "hic kaynak durumu yok -- collector hic calismadi mi?",
            "sources": {},
            "healthy_source_count": 0,
            "total_source_count": 0,
        }

    per_source = {sid: source_health(st, now, stale_after_minutes) for sid, st in sources.items()}
    total = len(per_source)
    healthy = sum(1 for h in per_source.values() if h["status"] == HEALTHY)
    unhealthy = sum(1 for h in per_source.values() if h["status"] == UNHEALTHY)
    available = sum(1 for st in sources.values() if _parse_iso(st.get("last_success_at")) is not None)

    # COMPLETENESS: kaynağın şu anda taze olup olmamasından ayrı olarak,
    # en az bir kez başarıyla veri katkısı yapıp yapamadığını ölçer.
    # Bayat (DEGRADED) bir kaynak hâlâ veri kapsamına katkı verir; bu
    # yüzden tazelik sorununu yanlışlıkla bütünlük sorunu saymayız.
    if available == total:
        completeness = HEALTHY
    elif available == 0:
        completeness = UNHEALTHY
    else:
        completeness = DEGRADED

    # FRESHNESS: en az bir kaynak yeterince taze mi?
    ages = [h["age_minutes"] for h in per_source.values() if h["age_minutes"] is not None]
    if not ages:
        freshness = UNHEALTHY
    elif min(ages) <= stale_after_minutes:
        freshness = HEALTHY
    else:
        freshness = DEGRADED

    # Operasyonel sağlık: kaynakların son denemelerindeki hata/bayatlık
    # ayrıca görünür kalsın. Böylece completeness'i düzeltirken aktif bir
    # kaynak hatasını overall status içinde yanlışlıkla gizlemeyiz.
    if healthy == total:
        operational = HEALTHY
    elif unhealthy == total:
        operational = UNHEALTHY
    else:
        operational = DEGRADED

    # Genel durum -- üç boyutun en kötüsü
    order = {HEALTHY: 0, DEGRADED: 1, UNHEALTHY: 2}
    status = max((freshness, completeness, operational), key=lambda s: order[s])

    return {
        "status": status,
        "freshness": freshness,
        "completeness": completeness,
        "operational": operational,
        "reason": f"{healthy}/{total} kaynak saglikli",
        "sources": per_source,
        "healthy_source_count": healthy,
        "available_source_count": available,
        "total_source_count": total,
    }
