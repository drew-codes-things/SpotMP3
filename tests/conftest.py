import json
import subprocess
from pathlib import Path

import pytest

from spotmp3.auth import BuiltinAuth
from spotmp3.config import Settings
from spotmp3.db import Database
from spotmp3.jobs import JobStore
from spotmp3.pipeline import Pipeline
from spotmp3.site_settings import SiteSettings
from spotmp3.tracks import Collection, Track
from spotmp3.web import create_app
from spotmp3.worker import Worker
from spotmp3.youtube import Match

PLENTY_OF_SPACE = 10 ** 12
CLIENT_HEADERS = {"X-SpotMP3": "1"}
TEST_PASSWORD = "correct horse battery"


def embed_page(entity: dict) -> str:
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def make_tone(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:a", "libopus", str(path)], check=True)
    return path


class FakeYouTube:
    def __init__(self, matches: dict[str, Match | None] | None = None):
        self.matches = matches or {}
        self.downloads: list[str] = []

    def find_match(self, track: Track) -> Match | None:
        if track.youtube_id:
            return Match(track.youtube_id, track.title, track.artist_line, track.duration_ms / 1000)
        return self.matches.get(track.title, Match("abcdefghijk", f"{track.artist_line} - {track.title}", "Some Channel", 2.0))

    def download_audio(self, match: Match, folder: Path) -> Path:
        self.downloads.append(match.video_id)
        return make_tone(folder / "source.opus")


def sample_track(title: str = "Song One", **extra) -> dict:
    return {"title": title, "artists": ["Artist"], "durationMs": 2000, **extra}


def fake_resolver(link, youtube, limit):
    tracks = [Track(title=f"Song {number}", artists=("Artist",), duration_ms=2000) for number in range(1, 4)]
    return Collection(kind="album", name="Test Album", tracks=tracks)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", retention_hours=24, storage_limit_mb=100, min_free_mb=50, max_open_jobs_per_user=3, max_tracks_per_job=10)


@pytest.fixture
def database(settings) -> Database:
    return Database(settings.database_path)


@pytest.fixture
def fake_youtube() -> FakeYouTube:
    return FakeYouTube()


@pytest.fixture
def worker(settings, database, fake_youtube) -> Worker:
    pipeline = Pipeline(fake_youtube, cover_lookup=lambda spotify_id: None, cover_download=lambda url, folder: None)
    return Worker(settings, database, pipeline, free_bytes=lambda path: PLENTY_OF_SPACE)


@pytest.fixture
def auth(database) -> BuiltinAuth:
    return BuiltinAuth(database)


@pytest.fixture
def jobs(database, settings) -> JobStore:
    return JobStore(database, settings)


@pytest.fixture
def app(settings, auth, jobs, worker, fake_youtube, database):
    application = create_app(settings, auth, jobs, worker, fake_youtube, SiteSettings(database, settings), resolver=fake_resolver)
    application.testing = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def set_up_admin(client, email: str = "admin@example.com"):
    response = client.post("/api/setup", json={"email": email, "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    assert response.status_code == 200, response.get_json()
    return response
