from __future__ import annotations

import logging
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
    def __init__(self, pipeline: DocumentPipeline, workers: int = 2) -> None:
        self.pipeline = pipeline
        self.executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="smartdoc"
        )
        self.observer: Observer | None = None
        self.folder: Path | None = None
        self._lock = Lock()

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

    def submit(self, path: Path) -> None:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        self.executor.submit(self.pipeline.process, path)

    def scan_existing(self, folder: Path) -> int:
        folder = folder.expanduser().resolve()
        candidates = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        for path in candidates:
            self.submit(path)
        return len(candidates)

    def close(self) -> None:
        self.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
