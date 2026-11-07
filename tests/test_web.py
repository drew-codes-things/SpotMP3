import io
import zipfile

from conftest import CLIENT_HEADERS, TEST_PASSWORD, sample_track, set_up_admin


def sign_in(client, email, password=TEST_PASSWORD):
    return client.post("/api/signin", json={"email": email, "password": password}, headers=CLIENT_HEADERS)


def test_fresh_install_sends_everyone_to_setup(client):
    assert client.get("/").headers["Location"].endswith("/setup")
    assert client.get("/signin").headers["Location"].endswith("/setup")
    assert client.get("/setup").status_code == 200
    assert client.get("/api/session").get_json() == {"mode": "builtin", "needsSetup": True, "user": None}


def test_setup_signs_in_and_closes_setup(client):
    response = set_up_admin(client)
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert client.get("/").status_code == 200
    assert client.get("/setup").headers["Location"].endswith("/")
    again = client.post("/api/setup", json={"email": "x@example.com", "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    assert again.status_code == 403


def test_signed_out_users_are_sent_to_sign_in(client, app):
    set_up_admin(client)
    fresh = app.test_client()
    assert fresh.get("/").headers["Location"].endswith("/signin")
    assert fresh.get("/api/jobs").status_code == 401
    assert fresh.post("/api/resolve", json={"link": "x"}, headers=CLIENT_HEADERS).status_code == 401


def test_writes_need_the_client_header(client):
    response = client.post("/api/setup", json={"email": "a@example.com", "password": TEST_PASSWORD, "confirm": TEST_PASSWORD})
    assert response.status_code == 403


def test_security_headers(client):
    response = client.get("/setup")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_resolve_convert_and_download(client, worker):
    set_up_admin(client)
    resolved = client.post("/api/resolve", json={"link": "https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa"}, headers=CLIENT_HEADERS).get_json()
    assert resolved["name"] == "Test Album" and len(resolved["tracks"]) == 3
    created = client.post("/api/jobs", json={"name": resolved["name"], "quality": "128", "tracks": resolved["tracks"]}, headers=CLIENT_HEADERS)
    assert created.status_code == 201
    job_id = created.get_json()["id"]
    while worker.process_next():
        pass
    detail = client.get(f"/api/jobs/{job_id}").get_json()
    assert detail["counts"] == {"done": 3}
    assert [item["fileName"] for item in detail["items"]] == ["Artist - Song 1.mp3", "Artist - Song 2.mp3", "Artist - Song 3.mp3"]
    single = client.get(f"/api/items/{detail['items'][0]['id']}/file")
    assert single.status_code == 200 and single.mimetype == "audio/mpeg"
    assert 'filename="Artist - Song 1.mp3"' in single.headers["Content-Disposition"]
    assert single.data[:3] == b"ID3"
    bundle = client.get(f"/api/jobs/{job_id}/zip")
    assert bundle.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(bundle.data)).namelist()
    assert names == ["Artist - Song 1.mp3", "Artist - Song 2.mp3", "Artist - Song 3.mp3"]


def test_job_input_is_validated(client):
    set_up_admin(client)
    cases = [
        {"quality": "999", "tracks": [sample_track()]},
        {"quality": "128", "tracks": []},
        {"quality": "128", "tracks": [sample_track() for _ in range(11)]},
        {"quality": "128", "tracks": [{"title": "x", "artists": [], "durationMs": 5}]},
        {"quality": "128", "tracks": [sample_track(youtubeId="not-an-id")]},
        {"quality": "128", "tracks": "nope"},
    ]
    for body in cases:
        assert client.post("/api/jobs", json=body, headers=CLIENT_HEADERS).status_code == 400, body
    assert client.post("/api/jobs", data="not json", headers={**CLIENT_HEADERS, "Content-Type": "application/json"}).status_code == 400


def test_open_job_limit(client):
    set_up_admin(client)
    for _ in range(3):
        assert client.post("/api/jobs", json={"quality": "128", "tracks": [sample_track()]}, headers=CLIENT_HEADERS).status_code == 201
    assert client.post("/api/jobs", json={"quality": "128", "tracks": [sample_track()]}, headers=CLIENT_HEADERS).status_code == 429


def test_people_only_see_their_own_jobs(client, app, worker):
    set_up_admin(client)
    client.post("/api/accounts", json={"email": "friend@example.com", "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    job_id = client.post("/api/jobs", json={"quality": "128", "tracks": [sample_track()]}, headers=CLIENT_HEADERS).get_json()["id"]
    worker.process_next()
    friend = app.test_client()
    assert sign_in(friend, "friend@example.com").status_code == 200
    assert friend.get("/api/jobs").get_json() == {"jobs": []}
    assert friend.get(f"/api/jobs/{job_id}").status_code == 404
    assert friend.get("/api/items/1/file").status_code == 404
    assert friend.get(f"/api/jobs/{job_id}/zip").status_code == 404
    assert friend.delete(f"/api/jobs/{job_id}", headers=CLIENT_HEADERS).status_code == 404
    assert friend.get("/api/accounts").status_code == 403


def test_retry_cancel_and_delete(client, worker, fake_youtube, settings):
    set_up_admin(client)
    fake_youtube.matches["Song One"] = None
    job_id = client.post("/api/jobs", json={"quality": "128", "tracks": [sample_track()]}, headers=CLIENT_HEADERS).get_json()["id"]
    worker.process_next()
    assert client.get(f"/api/jobs/{job_id}").get_json()["items"][0]["status"] == "failed"
    del fake_youtube.matches["Song One"]
    assert client.post("/api/items/1/retry", headers=CLIENT_HEADERS).status_code == 200
    assert client.post("/api/items/1/retry", headers=CLIENT_HEADERS).status_code == 409
    worker.process_next()
    assert client.get(f"/api/jobs/{job_id}").get_json()["items"][0]["status"] == "done"
    assert client.delete(f"/api/jobs/{job_id}", headers=CLIENT_HEADERS).status_code == 200
    assert client.get("/api/jobs").get_json() == {"jobs": []}
    assert not (settings.files_dir / str(job_id)).exists()


def test_accounts_admin(client, app):
    set_up_admin(client)
    added = client.post("/api/accounts", json={"email": "friend@example.com", "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    assert added.status_code == 201
    listed = client.get("/api/accounts").get_json()["accounts"]
    assert [account["email"] for account in listed] == ["admin@example.com", "friend@example.com"]
    assert "password" not in str(listed).lower()
    assert client.delete(f"/api/accounts/{added.get_json()['id']}", headers=CLIENT_HEADERS).status_code == 200
    assert sign_in(app.test_client(), "friend@example.com").status_code == 401


def test_sign_out(client):
    set_up_admin(client)
    assert client.post("/api/signout", headers=CLIENT_HEADERS).status_code == 200
    assert client.get("/api/jobs").status_code == 401


def test_config_reports_qualities_and_spotify_setup(client):
    set_up_admin(client)
    config = client.get("/api/config").get_json()
    assert [quality["key"] for quality in config["qualities"]] == ["128", "192", "256", "320", "v0"]
    assert config["defaultQuality"] == "320" and config["spotifyClientId"] == "" and config["canManageAccounts"] is True


def test_resolve_needs_a_link(client):
    set_up_admin(client)
    assert client.post("/api/resolve", json={"link": ""}, headers=CLIENT_HEADERS).status_code == 400
    assert client.post("/api/resolve", json={"link": "x" * 3000}, headers=CLIENT_HEADERS).status_code == 400
