import json

from .audio import QUALITIES
from .config import Settings
from .db import Database, now
from .tracks import TrackError, track_from_json

MAX_JOB_NAME_LENGTH = 200
OPEN_STATUSES = ("queued", "working")
RETRYABLE_STATUSES = ("failed", "cancelled")


class JobError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _clean_name(name) -> str:
    text = " ".join(name.split()) if isinstance(name, str) else ""
    return text[:MAX_JOB_NAME_LENGTH] or "Untitled"


class JobStore:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def _open_job_count(self, connection, owner: str) -> int:
        return connection.execute(
            "SELECT COUNT(DISTINCT jobs.id) FROM jobs JOIN items ON items.job_id = jobs.id "
            "WHERE jobs.owner = ? AND jobs.deleted = 0 AND jobs.cancelled = 0 AND items.status IN ('queued', 'working')",
            (owner,),
        ).fetchone()[0]

    def create(self, owner: str, name, quality, raw_tracks) -> int:
        if quality not in QUALITIES:
            raise JobError("pick one of the listed qualities")
        if not isinstance(raw_tracks, list) or not raw_tracks:
            raise JobError("pick at least one track")
        if len(raw_tracks) > self.settings.max_tracks_per_job:
            raise JobError(f"one job can hold at most {self.settings.max_tracks_per_job} tracks")
        try:
            tracks = [track_from_json(raw) for raw in raw_tracks]
        except TrackError as error:
            raise JobError(str(error)) from error
        with self.database.connect() as connection:
            if self._open_job_count(connection, owner) >= self.settings.max_open_jobs_per_user:
                raise JobError(f"you already have {self.settings.max_open_jobs_per_user} jobs running, wait for one to finish", status=429)
            job_id = connection.execute("INSERT INTO jobs (owner, name, quality, created_at) VALUES (?, ?, ?, ?)",
                                        (owner, _clean_name(name), quality, now())).lastrowid
            connection.executemany("INSERT INTO items (job_id, position, track_json) VALUES (?, ?, ?)",
                                   [(job_id, position, json.dumps(track.to_json())) for position, track in enumerate(tracks, start=1)])
        return job_id

    def _owned_job(self, connection, owner: str, job_id: int):
        row = connection.execute("SELECT * FROM jobs WHERE id = ? AND owner = ? AND deleted = 0", (job_id, owner)).fetchone()
        if row is None:
            raise JobError("no such job", status=404)
        return row

    def _counts(self, connection, job_id: int) -> dict:
        rows = connection.execute("SELECT status, COUNT(*) AS total FROM items WHERE job_id = ? GROUP BY status", (job_id,)).fetchall()
        return {row["status"]: row["total"] for row in rows}

    def _summary(self, connection, job) -> dict:
        counts = self._counts(connection, job["id"])
        return {"id": job["id"], "name": job["name"], "quality": job["quality"], "qualityLabel": QUALITIES[job["quality"]][0],
                "createdAt": job["created_at"], "cancelled": bool(job["cancelled"]), "counts": counts, "total": sum(counts.values())}

    def list_for(self, owner: str) -> list[dict]:
        with self.database.connect() as connection:
            jobs = connection.execute("SELECT * FROM jobs WHERE owner = ? AND deleted = 0 ORDER BY id DESC", (owner,)).fetchall()
            return [self._summary(connection, job) for job in jobs]

    def detail(self, owner: str, job_id: int) -> dict:
        with self.database.connect() as connection:
            job = self._owned_job(connection, owner, job_id)
            items = connection.execute("SELECT * FROM items WHERE job_id = ? ORDER BY position", (job_id,)).fetchall()
            summary = self._summary(connection, job)
        summary["items"] = [self._item_json(item) for item in items]
        return summary

    def _item_json(self, item) -> dict:
        track = json.loads(item["track_json"])
        return {"id": item["id"], "position": item["position"], "title": track["title"], "artists": track["artists"],
                "durationMs": track["durationMs"], "coverUrl": track.get("coverUrl"), "status": item["status"], "error": item["error"],
                "youtubeId": item["youtube_id"], "youtubeTitle": item["youtube_title"], "fileName": item["file_name"],
                "fileBytes": item["file_bytes"]}

    def cancel(self, owner: str, job_id: int) -> None:
        with self.database.connect() as connection:
            self._owned_job(connection, owner, job_id)
            connection.execute("UPDATE jobs SET cancelled = 1 WHERE id = ?", (job_id,))
            connection.execute("UPDATE items SET status = 'cancelled', finished_at = ? WHERE job_id = ? AND status = 'queued'", (now(), job_id))

    def delete(self, owner: str, job_id: int) -> None:
        with self.database.connect() as connection:
            self._owned_job(connection, owner, job_id)
            connection.execute("UPDATE jobs SET deleted = 1, cancelled = 1 WHERE id = ?", (job_id,))
            connection.execute("UPDATE items SET status = 'cancelled', finished_at = ? WHERE job_id = ? AND status = 'queued'", (now(), job_id))

    def delete_owner(self, owner: str) -> None:
        with self.database.connect() as connection:
            job_ids = [row["id"] for row in connection.execute("SELECT id FROM jobs WHERE owner = ? AND deleted = 0", (owner,)).fetchall()]
        for job_id in job_ids:
            self.delete(owner, job_id)

    def _owned_item(self, connection, owner: str, item_id: int):
        row = connection.execute("SELECT items.* FROM items JOIN jobs ON jobs.id = items.job_id WHERE items.id = ? AND jobs.owner = ? AND jobs.deleted = 0",
                                 (item_id, owner)).fetchone()
        if row is None:
            raise JobError("no such track", status=404)
        return row

    def retry(self, owner: str, item_id: int) -> None:
        with self.database.connect() as connection:
            item = self._owned_item(connection, owner, item_id)
            if item["status"] not in RETRYABLE_STATUSES:
                raise JobError("only failed or cancelled tracks can be retried", status=409)
            if connection.execute("SELECT 1 FROM items WHERE job_id = ? AND status IN ('queued', 'working')", (item["job_id"],)).fetchone() is None \
                    and self._open_job_count(connection, owner) >= self.settings.max_open_jobs_per_user:
                raise JobError(f"you already have {self.settings.max_open_jobs_per_user} jobs running, wait for one to finish", status=429)
            connection.execute("UPDATE jobs SET cancelled = 0 WHERE id = ?", (item["job_id"],))
            connection.execute("UPDATE items SET status = 'queued', error = NULL, finished_at = NULL WHERE id = ?", (item_id,))

    def item_file(self, owner: str, item_id: int) -> tuple[str, str]:
        with self.database.connect() as connection:
            item = self._owned_item(connection, owner, item_id)
        if item["status"] != "done" or not item["file_path"]:
            raise JobError("that track has no file to download", status=404)
        return item["file_path"], item["file_name"]

    def job_files(self, owner: str, job_id: int) -> tuple[str, list[tuple[str, str]]]:
        with self.database.connect() as connection:
            job = self._owned_job(connection, owner, job_id)
            rows = connection.execute("SELECT file_path, file_name FROM items WHERE job_id = ? AND status = 'done' AND file_path IS NOT NULL ORDER BY position",
                                      (job_id,)).fetchall()
        if not rows:
            raise JobError("this job has no finished tracks yet", status=404)
        return job["name"], [(row["file_path"], row["file_name"]) for row in rows]
