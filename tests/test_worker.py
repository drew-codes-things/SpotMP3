import json

from conftest import sample_track
from spotmp3.db import now
from spotmp3.pipeline import Pipeline
from spotmp3.worker import MEGABYTE, Worker

OWNER = "builtin:1"


def item_rows(database):
    with database.connect() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM items ORDER BY id")]


def test_worker_converts_queued_tracks_in_order(jobs, worker, database, settings):
    job_id = jobs.create(OWNER, "Album", "192", [sample_track("First"), sample_track("Second")])
    first = worker.process_next()
    second = worker.process_next()
    assert (first, second, worker.process_next()) == (1, 2, None)
    rows = item_rows(database)
    assert [row["status"] for row in rows] == ["done", "done"]
    assert rows[0]["file_name"] == "Artist - First.mp3"
    assert (settings.files_dir / str(job_id) / "Artist - First.mp3").stat().st_size == rows[0]["file_bytes"]
    assert list(settings.work_dir.iterdir()) == []


def test_same_name_twice_gets_a_number(jobs, worker, database):
    jobs.create(OWNER, "Twice", "128", [sample_track("Same"), sample_track("Same")])
    worker.process_next()
    worker.process_next()
    assert [row["file_name"] for row in item_rows(database)] == ["Artist - Same.mp3", "Artist - Same (2).mp3"]


def test_no_match_fails_the_item_with_a_reason(jobs, worker, database, fake_youtube):
    fake_youtube.matches["Nowhere"] = None
    jobs.create(OWNER, "x", "128", [sample_track("Nowhere")])
    worker.process_next()
    row = item_rows(database)[0]
    assert row["status"] == "failed" and "no close enough match" in row["error"]


def test_youtube_tracks_download_their_own_video(jobs, worker, fake_youtube, database):
    jobs.create(OWNER, "x", "128", [sample_track("Video", youtubeId="yybnK-DhphM")])
    worker.process_next()
    assert fake_youtube.downloads == ["yybnK-DhphM"]
    assert item_rows(database)[0]["youtube_id"] == "yybnK-DhphM"


def test_recover_requeues_interrupted_work(jobs, worker, database, settings):
    jobs.create(OWNER, "x", "128", [sample_track()])
    database.update_item(1, status="working")
    (settings.work_dir / "1").mkdir()
    assert worker.recover() == 1
    assert item_rows(database)[0]["status"] == "queued"
    assert list(settings.work_dir.iterdir()) == []


def test_low_disk_space_waits_instead_of_converting(jobs, settings, database, fake_youtube, monkeypatch):
    low = Worker(settings, database, Pipeline(fake_youtube, cover_download=lambda url, folder: None), free_bytes=lambda path: 10 * MEGABYTE)
    monkeypatch.setattr(low._stop, "wait", lambda seconds: None)
    jobs.create(OWNER, "x", "128", [sample_track()])
    assert low.process_next() is None
    assert item_rows(database)[0]["status"] == "queued"


def test_cancelled_jobs_are_skipped(jobs, worker, database):
    job_id = jobs.create(OWNER, "x", "128", [sample_track(), sample_track("Two")])
    jobs.cancel(OWNER, job_id)
    assert worker.process_next() is None
    assert item_rows(database) == []


def test_job_cancelled_mid_conversion_keeps_no_file(jobs, worker, database, settings, fake_youtube):
    job_id = jobs.create(OWNER, "x", "128", [sample_track()])
    original = fake_youtube.download_audio

    def cancel_while_downloading(match, folder):
        jobs.cancel(OWNER, job_id)
        return original(match, folder)

    fake_youtube.download_audio = cancel_while_downloading
    worker.process_next()
    assert item_rows(database)[0]["status"] == "cancelled"
    assert not (settings.files_dir / str(job_id)).exists() or not any((settings.files_dir / str(job_id)).iterdir())


def test_cleanup_expires_old_files_and_removes_old_jobs(jobs, worker, database, settings):
    job_id = jobs.create(OWNER, "x", "128", [sample_track()])
    worker.process_next()
    long_ago = now() - 3 * 24 * 3600
    with database.connect() as connection:
        connection.execute("UPDATE items SET finished_at = ?", (long_ago,))
    worker.cleanup()
    assert item_rows(database)[0]["status"] == "expired"
    assert not any((settings.files_dir / str(job_id)).iterdir())
    with database.connect() as connection:
        connection.execute("UPDATE jobs SET created_at = ?", (long_ago,))
    worker.cleanup()
    assert item_rows(database) == []
    assert not (settings.files_dir / str(job_id)).exists()


def test_cleanup_keeps_storage_under_the_limit(jobs, worker, database):
    jobs.create(OWNER, "x", "128", [sample_track("Old"), sample_track("New")])
    worker.process_next()
    worker.process_next()
    with database.connect() as connection:
        connection.execute("UPDATE items SET file_bytes = ? WHERE id = 1", (80 * MEGABYTE,))
        connection.execute("UPDATE items SET file_bytes = ? WHERE id = 2", (30 * MEGABYTE,))
    worker.cleanup()
    assert [row["status"] for row in item_rows(database)] == ["expired", "done"]


def test_file_paths_cannot_leave_the_files_folder(worker, settings):
    (settings.data_dir / "secret.txt").write_text("x")
    assert worker.file_for("../secret.txt") is None
    assert worker.file_for("/etc/passwd") is None
    assert worker.file_for(None) is None


def test_stored_track_json_is_validated_again(jobs, worker, database):
    jobs.create(OWNER, "x", "128", [sample_track()])
    with database.connect() as connection:
        connection.execute("UPDATE items SET track_json = ?", (json.dumps({"title": ""}),))
    worker.process_next()
    assert item_rows(database)[0]["status"] == "failed"


def test_cleanup_keeps_an_old_job_whose_track_only_just_finished(jobs, worker, database, settings):
    job_id = jobs.create(OWNER, "x", "128", [sample_track()])
    long_ago = now() - 3 * 24 * 3600
    with database.connect() as connection:
        connection.execute("UPDATE jobs SET created_at = ?", (long_ago,))
    worker.process_next()
    worker.cleanup()
    assert [row["status"] for row in item_rows(database)] == ["done"]
    assert len(list((settings.files_dir / str(job_id)).iterdir())) == 1
    assert jobs.detail(OWNER, job_id)["counts"] == {"done": 1}
