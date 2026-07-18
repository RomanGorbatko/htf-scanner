import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path


class ScannerAlreadyRunning(RuntimeError):
    pass


class ProcessLock:
    def __init__(self, path: Path, stale_after: timedelta) -> None:
        self.path = path
        self.stale_after = stale_after
        self._owned = False

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_stale()
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise ScannerAlreadyRunning(f"scanner lock already exists: {self.path}") from error
        payload = json.dumps(
            {"pid": os.getpid(), "created_at": datetime.now(UTC).isoformat()},
            sort_keys=True,
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.close(descriptor)
        self._owned = True
        return self

    def __exit__(self, *_args: object) -> None:
        if self._owned:
            self.path.unlink(missing_ok=True)
            self._owned = False

    def _clear_stale(self) -> None:
        if not self.path.exists():
            return
        modified = datetime.fromtimestamp(self.path.stat().st_mtime, tz=UTC)
        if datetime.now(UTC) - modified > self.stale_after:
            self.path.unlink(missing_ok=True)
