import threading

import pytest

from conftest import CLIENT_HEADERS, TEST_PASSWORD, fake_resolver, set_up_admin
from spotmp3.auth import SESSION_COOKIE
from spotmp3.config import Settings
from spotmp3.site_settings import SiteSettings
from spotmp3.web import create_app

LINK = "https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa"
TRACK = {"title": "Song", "artists": ["Artist"], "durationMs": 2000}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def limited_settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", resolves_per_minute=3, jobs_per_minute=2, max_open_jobs_per_user=50)


def build_app(limited_settings, auth, jobs, worker, fake_youtube, database, clock, resolver=fake_resolver):
    application = create_app(limited_settings, auth, jobs, worker, fake_youtube, SiteSettings(database, limited_settings),
                             resolver=resolver, clock=clock)
    application.testing = True
    return application


def resolve(client):
    return client.post("/api/resolve", json={"link": LINK}, headers=CLIENT_HEADERS)


def test_reading_links_is_limited_per_minute(limited_settings, auth, jobs, worker, fake_youtube, database, clock):
    client = build_app(limited_settings, auth, jobs, worker, fake_youtube, database, clock).test_client()
    set_up_admin(client)
    assert [resolve(client).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert "minute" in resolve(client).get_json()["error"]
    clock.now += 61
    assert resolve(client).status_code == 200


def test_one_persons_limit_does_not_block_another(limited_settings, auth, jobs, worker, fake_youtube, database, clock):
    app = build_app(limited_settings, auth, jobs, worker, fake_youtube, database, clock)
    admin = app.test_client()
    set_up_admin(admin)
    admin.post("/api/accounts", json={"email": "friend@example.com", "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    for _ in range(3):
        resolve(admin)
    assert resolve(admin).status_code == 429
    friend = app.test_client()
    friend.post("/api/signin", json={"email": "friend@example.com", "password": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    assert resolve(friend).status_code == 200


def test_creating_jobs_is_limited_per_minute(limited_settings, auth, jobs, worker, fake_youtube, database, clock):
    client = build_app(limited_settings, auth, jobs, worker, fake_youtube, database, clock).test_client()
    set_up_admin(client)
    statuses = [client.post("/api/jobs", json={"quality": "128", "tracks": [TRACK]}, headers=CLIENT_HEADERS).status_code
                for _ in range(3)]
    assert statuses == [201, 201, 429]
    clock.now += 61
    assert client.post("/api/jobs", json={"quality": "128", "tracks": [TRACK]}, headers=CLIENT_HEADERS).status_code == 201


def test_only_one_link_is_read_at_a_time_per_person(limited_settings, auth, jobs, worker, fake_youtube, database, clock):
    started, release = threading.Event(), threading.Event()

    def slow_resolver(link, youtube, limit):
        started.set()
        release.wait(5)
        return fake_resolver(link, youtube, limit)

    app = build_app(limited_settings, auth, jobs, worker, fake_youtube, database, clock, resolver=slow_resolver)
    first = app.test_client()
    set_up_admin(first)
    second = app.test_client()
    second.set_cookie(SESSION_COOKIE, first.get_cookie(SESSION_COOKIE).value)
    results = {}
    reader = threading.Thread(target=lambda: results.setdefault("first", resolve(first).status_code))
    reader.start()
    assert started.wait(5)
    overlapping = resolve(second)
    release.set()
    reader.join(5)
    assert overlapping.status_code == 429
    assert "still reading" in overlapping.get_json()["error"]
    assert results["first"] == 200
    assert resolve(second).status_code == 200


def test_limits_are_read_from_the_environment(monkeypatch, tmp_path):
    from spotmp3.config import load_settings
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESOLVES_PER_MINUTE", "4")
    monkeypatch.setenv("JOBS_PER_MINUTE", "7")
    settings = load_settings()
    assert (settings.resolves_per_minute, settings.jobs_per_minute) == (4, 7)
