from conftest import CLIENT_HEADERS, set_up_admin, sample_track
from spotmp3.pipeline import Pipeline
from spotmp3.site_settings import SiteSettings
from spotmp3.web import create_app
from spotmp3.worker import MEGABYTE, Worker

OWNER = "builtin:1"
CYCLES = 8


def row_counts(database):
    with database.connect() as connection:
        return (connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])


def test_create_and_cancel_in_a_loop_leaves_nothing_behind(client, worker, database, settings):
    set_up_admin(client)
    tracks = [sample_track(f"Song {number}") for number in range(settings.max_tracks_per_job)]
    for _ in range(CYCLES):
        created = client.post("/api/jobs", json={"quality": "128", "tracks": tracks}, headers=CLIENT_HEADERS)
        assert created.status_code == 201
        assert client.post(f"/api/jobs/{created.get_json()['id']}/cancel", headers=CLIENT_HEADERS).status_code == 200
    worker.cleanup()
    assert row_counts(database) == (0, 0)
    assert client.get("/api/jobs").get_json() == {"jobs": []}


def test_cancel_keeps_finished_tracks_and_drops_the_ones_never_started(jobs, worker, database):
    job_id = jobs.create(OWNER, "x", "128", [sample_track("Done"), sample_track("Waiting")])
    worker.process_next()
    jobs.cancel(OWNER, job_id)
    detail = jobs.detail(OWNER, job_id)
    assert detail["counts"] == {"done": 1}
    assert [item["title"] for item in detail["items"]] == ["Done"]
    assert row_counts(database) == (1, 1)


def test_no_new_job_while_the_disk_is_below_the_free_space_floor(settings, auth, jobs, fake_youtube, database):
    low_disk = Worker(settings, database, Pipeline(fake_youtube, cover_download=lambda url, folder: None),
                      free_bytes=lambda path: (settings.min_free_mb - 1) * MEGABYTE)
    app = create_app(settings, auth, jobs, low_disk, fake_youtube, SiteSettings(database, settings))
    client = app.test_client()
    set_up_admin(client)
    response = client.post("/api/jobs", json={"quality": "128", "tracks": [sample_track()]}, headers=CLIENT_HEADERS)
    assert response.status_code == 507
    assert "disk" in response.get_json()["error"]
    assert row_counts(database) == (0, 0)


def test_the_database_counts_towards_the_storage_limit(jobs, worker, database, monkeypatch):
    jobs.create(OWNER, "x", "128", [sample_track("Old"), sample_track("New")])
    worker.process_next()
    worker.process_next()
    with database.connect() as connection:
        connection.execute("UPDATE items SET file_bytes = ? WHERE id = 1", (60 * MEGABYTE,))
        connection.execute("UPDATE items SET file_bytes = ? WHERE id = 2", (30 * MEGABYTE,))
    monkeypatch.setattr(worker, "database_bytes", lambda: 20 * MEGABYTE, raising=False)
    worker.cleanup()
    with database.connect() as connection:
        statuses = [row["status"] for row in connection.execute("SELECT status FROM items ORDER BY id")]
    assert statuses == ["expired", "done"]


def test_database_size_includes_its_write_ahead_log(worker, database, settings):
    with database.connect() as connection:
        connection.execute("SELECT 1")
    on_disk = sum(path.stat().st_size for path in settings.data_dir.glob("spotmp3.db*"))
    assert worker.database_bytes() == on_disk > 0
