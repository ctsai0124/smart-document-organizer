from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .fileops import SUPPORTED_EXTENSIONS
from .pipeline import DocumentPipeline

LOGGER = logging.getLogger(__name__)


class ScanEventHandler(FileSystemEventHandler):
    def __init__(self, submit: Callable[[Path], None]) -> None:
        super().__init__()
        self.submit = submit

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory and hasattr(event, "dest_path"):
            self.submit(Path(event.dest_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.submit(Path(event.src_path))


class FolderWatcher:
    def __init__(
        self,
        pipeline: DocumentPipeline,
        workers: int = 2,
        cooldown_seconds: float = 1.5,
    ) -> None:
        self.pipeline = pipeline
        self.executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="smartdoc"
        )
        self.observer: Observer | None = None
        self.folder: Path | None = None
        self._lock = Lock()
        self._pending: set[str] = set()
        self._recent: dict[str, float] = {}
        self._cooldown_seconds = cooldown_seconds

    @property
    def running(self) -> bool:
        return bool(self.observer and self.observer.is_alive())

    def start(self, folder: Path, *, scan_existing: bool = False) -> None:
        folder = folder.expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.stop()
            handler = ScanEventHandler(self.submit)
            self.observer = Observer()
            self.observer.schedule(handler, str(folder), recursive=False)
            self.observer.start()
            self.folder = folder
        if scan_existing:
            self.scan_existing(folder)

    def stop(self) -> None:
        observer = self.observer
        self.observer = None
        if observer:
            observer.stop()
            observer.join(timeout=5)

    def submit(self, path: Path, *, force: bool = False) -> bool:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False
        key = str(path.expanduser().resolve()).casefold()
        now = time.monotonic()
        with self._lock:
            self._recent = {
                recent_key: completed_at
                for recent_key, completed_at in self._recent.items()
                if now - completed_at < self._cooldown_seconds
            }
            if key in self._pending or (not force and key in self._recent):
                return False
            self._pending.add(key)
        self.executor.submit(self._run_pipeline, path, key, force)
        return True

    def _run_pipeline(self, path: Path, key: str, force: bool) -> None:
        try:
            if force:
                self.pipeline.process(path, force=True)
            else:
                self.pipeline.process(path)
        finally:
            with self._lock:
                self._pending.discard(key)
                self._recent[key] = time.monotonic()

    def scan_existing(self, folder: Path) -> int:
        folder = folder.expanduser().resolve()
        candidates = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        return sum(1 for path in candidates if self.submit(path))

    def close(self) -> None:
        self.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
