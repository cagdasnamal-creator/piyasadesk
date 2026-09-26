"""
Single-instance lock -- ayni anda iki collector calismasini onler.

PULSE'ta ayni desen zaten var (daily runner'in tek-instance kilidi).
Gerekce: iki collector es zamanli calisirsa ayni haberi iki kez yazabilir
(read_existing_ids ile append arasindaki yarista), state dosyasini
birbirinin uzerine yazabilir ve raw klasorunu gereksiz sisirir.

Tasarim:
  - os.O_EXCL ile atomik olusturma (yaris kosulu yok)
  - Kilit dosyasina PID + zaman damgasi yazilir
  - BAYAT kilit: surec cokerse (Ctrl+C degil, kill/BSOD) kilit dosyasi
    kalir. Belirli bir yastan sonra bayat sayilir ve DEVRALINIR --
    aksi halde arac kalici olarak calisamaz hale gelirdi.
  - Bayat devralma SESSIZCE olmaz, acikca uyarir.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCK_PATH = BASE_DIR / "data" / "collector.lock"

# Bir kilit bu yastan eskiyse, sahibi cokmus kabul edilir.
# Toplama dongusu tipik olarak saniyeler surer; 30 dk cok genis bir pay.
STALE_AFTER_SECONDS = 30 * 60


class CollectorAlreadyRunning(RuntimeError):
    """Baska bir collider ornegi zaten calisiyor."""


class SingleInstanceLock:
    """Context manager:

        with SingleInstanceLock():
            collect_once()
    """

    def __init__(self, path: Path | None = None, stale_after: int = STALE_AFTER_SECONDS):
        self.path = Path(path) if path else LOCK_PATH
        self.stale_after = stale_after
        self.acquired = False

    def _read_lock(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _is_stale(self) -> tuple[bool, float]:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return True, 0.0
        return age > self.stale_after, age

    def acquire(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            stale, age = self._is_stale()
            if not stale:
                info = self._read_lock()
                raise CollectorAlreadyRunning(
                    f"Baska bir collector zaten calisiyor "
                    f"(pid={info.get('pid')}, {age:.0f} sn once baslatildi). "
                    f"Gercekten calismiyorsa {self.path} dosyasini silin."
                )
            # BAYAT kilit -- devral, ama SESSIZCE degil
            print(f"[KILIT] Bayat kilit devralindi ({age:.0f} sn eski) -- "
                  f"onceki surec muhtemelen coktu.")
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(),
                       "acquired_at": datetime.now(timezone.utc).isoformat()}, f)
        self.acquired = True
        return self

    def touch(self) -> None:
        """Uzun suren dongulerde kilidi taze tutar (bayat sayilmasin diye)."""
        if self.acquired and self.path.exists():
            os.utime(self.path, None)

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False

    def __enter__(self) -> "SingleInstanceLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
