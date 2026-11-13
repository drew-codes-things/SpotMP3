import io
import tempfile
import zipfile

import pytest

from conftest import CLIENT_HEADERS, sample_track, set_up_admin


@pytest.fixture
def no_temporary_files(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the zip download wrote a temporary file")

    for name in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, refuse)


def finished_job(client, worker, name="Road Trip", titles=("One", "Two", "Three")):
    set_up_admin(client)
    created = client.post("/api/jobs", json={"name": name, "quality": "128", "tracks": [sample_track(title) for title in titles]},
                          headers=CLIENT_HEADERS)
    job_id = created.get_json()["id"]
    while worker.process_next():
        pass
    return job_id


def test_the_zip_is_streamed_without_a_temporary_copy(client, worker, settings, no_temporary_files):
    job_id = finished_job(client, worker)
    response = client.get(f"/api/jobs/{job_id}/zip")
    assert response.status_code == 200
    assert response.is_streamed
    assert response.mimetype == "application/zip"
    assert 'filename="Road Trip.zip"' in response.headers["Content-Disposition"]
    bundle = zipfile.ZipFile(io.BytesIO(response.get_data()))
    assert bundle.testzip() is None
    assert bundle.namelist() == ["Artist - One.mp3", "Artist - Two.mp3", "Artist - Three.mp3"]
    stored = settings.files_dir / str(job_id) / "Artist - Two.mp3"
    assert bundle.read("Artist - Two.mp3") == stored.read_bytes()
    assert list(settings.work_dir.iterdir()) == []


def test_a_job_name_outside_ascii_still_downloads(client, worker, no_temporary_files):
    job_id = finished_job(client, worker, name="Café Mix 東京", titles=("One",))
    response = client.get(f"/api/jobs/{job_id}/zip")
    assert response.status_code == 200
    assert "filename*=UTF-8''Caf%C3%A9%20Mix%20%E6%9D%B1%E4%BA%AC.zip" in response.headers["Content-Disposition"]
    assert zipfile.ZipFile(io.BytesIO(response.get_data())).namelist() == ["Artist - One.mp3"]
