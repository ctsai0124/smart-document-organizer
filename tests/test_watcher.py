from pathlib import Path
from threading import Event, Lock

from smartdoc.watcher import FolderWatcher


class RecordingPipeline:
    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.paths: list[Path] = []
        self.lock = Lock()
        self.done = Event()

    def process(self, path: Path) -> None:
        with self.lock:
            self.paths.append(path)
            if len(self.paths) >= self.expected:
                self.done.set()


def test_scan_existing_submits_only_supported_files(tmp_path: Path) -> None:
    (tmp_path / "scan.pdf").write_bytes(b"pdf")
    (tmp_path / "photo.JPG").write_bytes(b"jpg")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "inside.pdf").write_bytes(b"not recursive")
    pipeline = RecordingPipeline(expected=2)
    watcher = FolderWatcher(pipeline, workers=1)  # type: ignore[arg-type]

    submitted = watcher.scan_existing(tmp_path)
    assert pipeline.done.wait(timeout=2)
    watcher.close()

    assert submitted == 2
    assert {path.name for path in pipeline.paths} == {"scan.pdf", "photo.JPG"}
