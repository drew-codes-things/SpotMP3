import json
import logging
import shutil
import threading
from pathlib import Path
from typing import Callable

from .audio import AudioError, safe_file_name, unique_path
from .config import Settings
from .db import Database, now
from .pipeline import ConversionError, Pipeline
from .tracks import TrackError, track_from_json
from .youtube import YouTubeError

IDLE_WAIT_SECONDS = 5
LOW_DISK_WAIT_SECONDS = 60
CLEANUP_INTERVAL_SECONDS = 10 * 60
MEGABYTE = 1024 * 1024
MAX_ERROR_LENGTH = 300
EXPECTED_FAILURES = (ConversionError, YouTubeError, AudioError, TrackError, OSError, ValueError)

log = logging.getLogger("spotmp3.worker")


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _short(error: Exception) -> str:
    return (str(error) or error.__class__.__name__)[:MAX_ERROR_LENGTH]


class Worker:
    def __init__(self, settings: Settings, database: Database, pipeline: Pipeline, free_bytes: Callable[[Path], int] = _free_bytes):
        self.settings = settings
        self.database = database
        self.pipeline = pipeline
        self._free_bytes = free_bytes
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_cleanup = 0.0
        settings.files_dir.mkdir(parents=True, exist_ok=True)
        settings.work_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._run, name="spotmp3-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def notify(self) -> None:
        self._wake.set()

    def recover(self) -> int:
        for leftover in self.settings.work_dir.iterdir():
            if leftover.is_dir():
                shutil.rmtree(leftover)
            else:
                leftover.unlink()
        with self.database.connect() as connection:
            return connection.execute("UPDATE items SET status = 'queued' WHERE status = 'working'").rowcount

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.process_next() is None:
                    self._wake.wait(IDLE_WAIT_SECONDS)
                    self._wake.clear()
            except Exception:
                log.exception("the worker loop hit an unexpected error")
                self._stop.wait(IDLE_WAIT_SECONDS)

    def has_free_space(self) -> bool:
        return self._free_bytes(self.settings.data_dir) >= self.settings.min_free_mb * MEGABYTE

    def _next_item(self):
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT items.id, items.job_id, items.track_json, jobs.quality FROM items JOIN jobs ON jobs.id = items.job_id "
                "WHERE items.status = 'queued' AND jobs.cancelled = 0 AND jobs.deleted = 0 ORDER BY items.id LIMIT 1"
            ).fetchone()

    def process_next(self) -> int | None:
        if now() - self._last_cleanup > CLEANUP_INTERVAL_SECONDS:
            self.cleanup()
        item = self._next_item()
        if item is None:
            return None
        if not self.has_free_space():
            self.cleanup()
            if not self.has_free_space():
                log.warning("less than %s MB free, waiting before converting more", self.settings.min_free_mb)
                self._stop.wait(LOW_DISK_WAIT_SECONDS)
                return None
        self.process(item)
        return item["id"]

    def _job_is_live(self, job_id: int) -> bool:
        with self.database.connect() as connection:
            row = connection.execute("SELECT cancelled, deleted FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row is not None and not row["cancelled"] and not row["deleted"]

    def _destination(self, job_id: int, file_name: str) -> Path:
        folder = self.settings.files_dir / str(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        return unique_path(folder, file_name)

    def process(self, item) -> None:
        item_id, job_id = item["id"], item["job_id"]
        self.database.update_item(item_id, status="working", error=None)
        folder = self.settings.work_dir / str(item_id)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            track = track_from_json(json.loads(item["track_json"]))
            converted = self.pipeline.convert(track, item["quality"], folder,
                                              on_match=lambda match: self.database.update_item(item_id, youtube_id=match.video_id, youtube_title=match.title))
            if not self._job_is_live(job_id):
                self.database.update_item(item_id, status="cancelled", finished_at=now())
                return
            destination = self._destination(job_id, safe_file_name(track.artist_line, track.title))
            shutil.move(converted.mp3_path, destination)
            self.database.update_item(item_id, status="done", file_name=destination.name,
                                      file_path=str(destination.relative_to(self.settings.files_dir)),
                                      file_bytes=destination.stat().st_size, finished_at=now())
        except EXPECTED_FAILURES as error:
            self.database.update_item(item_id, status="failed", error=_short(error), finished_at=now())
        except Exception as error:
            log.exception("item %s failed unexpectedly", item_id)
            self.database.update_item(item_id, status="failed", error=f"unexpected error: {_short(error)}", finished_at=now())
        finally:
            if folder.exists():
                shutil.rmtree(folder)

    def file_for(self, relative_path: str | None) -> Path | None:
        if not relative_path:
            return None
        root = self.settings.files_dir.resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    def _expire(self, connection, item_id: int, relative_path: str | None) -> None:
        path = self.file_for(relative_path)
        if path:
            path.unlink()
        connection.execute("UPDATE items SET status = 'expired', file_path = NULL WHERE id = ?", (item_id,))

    def cleanup(self) -> None:
        self._last_cleanup = now()
        cutoff = now() - self.settings.retention_hours * 3600
        limit = self.settings.storage_limit_mb * MEGABYTE
        with self.database.connect() as connection:
            for row in connection.execute("SELECT id, file_path FROM items WHERE status = 'done' AND finished_at < ?", (cutoff,)).fetchall():
                self._expire(connection, row["id"], row["file_path"])
            stored = connection.execute("SELECT id, file_path, file_bytes FROM items WHERE status = 'done' ORDER BY finished_at").fetchall()
            total = sum(row["file_bytes"] or 0 for row in stored)
            for row in stored:
                if total <= limit:
                    break
                self._expire(connection, row["id"], row["file_path"])
                total -= row["file_bytes"] or 0
            finished_jobs = connection.execute(
                "SELECT id FROM jobs WHERE (deleted = 1 OR created_at < ?) AND NOT EXISTS (SELECT 1 FROM items WHERE items.job_id = jobs.id "
                "AND (items.status = 'working' OR (items.status = 'queued' AND jobs.deleted = 0 AND jobs.cancelled = 0)))",
                (cutoff,),
            ).fetchall()
            for row in finished_jobs:
                self._remove_job(connection, row["id"])

    def _remove_job(self, connection, job_id: int) -> None:
        folder = self.settings.files_dir / str(job_id)
        if folder.is_dir():
            shutil.rmtree(folder)
        connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
