import logging
from dataclasses import replace

import pytest

from conftest import CLIENT_HEADERS, TEST_PASSWORD, set_up_admin, setup_code_from_the_log
from spotmp3.auth import AuthError, StarfireAuth
from spotmp3.config import load_settings
from spotmp3.site_settings import SiteSettings
from spotmp3 import web
from spotmp3.web import create_app

ADMIN = "admin@example.com"
REBINDING_HOST = "http://rebind.evil.example:8095"


def setup_details(code, email=ADMIN):
    return {"code": code, "email": email, "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}


def status_of(action) -> int:
    try:
        action()
    except AuthError as error:
        return error.status
    return 200


def app_for(settings, auth, jobs, worker, fake_youtube, database):
    application = create_app(settings, auth, jobs, worker, fake_youtube, SiteSettings(database, settings))
    application.testing = True
    return application


@pytest.mark.parametrize("code", [None, "", "not-the-code"])
def test_setup_needs_the_code_from_the_log(client, code):
    setup_code_from_the_log(client)
    refused = client.post("/api/setup", json=setup_details(code), headers=CLIENT_HEADERS)
    assert refused.status_code == 401
    assert client.get("/api/session").get_json()["needsSetup"] is True


def test_the_setup_page_writes_the_code_to_the_log(client, caplog):
    caplog.set_level(logging.WARNING)
    assert client.get("/setup").status_code == 200
    assert "enter the setup code" in caplog.text


def test_a_rebinding_host_name_cannot_set_up_or_sign_in(client):
    code = setup_code_from_the_log(client)
    assert client.post("/api/setup", json=setup_details(code), headers=CLIENT_HEADERS, base_url=REBINDING_HOST).status_code == 421
    assert client.get("/setup", base_url=REBINDING_HOST).status_code == 421
    set_up_admin(client)
    signin = {"email": ADMIN, "password": TEST_PASSWORD}
    assert client.post("/api/signin", json=signin, headers=CLIENT_HEADERS, base_url=REBINDING_HOST).status_code == 421


def test_the_setup_code_works_only_once(auth, database, caplog):
    caplog.set_level(logging.WARNING)
    first_code = auth.setup_code()
    auth.create_first_admin(first_code, ADMIN, TEST_PASSWORD, TEST_PASSWORD, "198.51.100.4")
    assert auth.setup_code() is None
    with database.connect() as connection:
        connection.execute("DELETE FROM sessions")
        connection.execute("DELETE FROM users")
    assert status_of(lambda: auth.create_first_admin(first_code, "intruder@example.com", TEST_PASSWORD, TEST_PASSWORD,
                                                     "203.0.113.9")) == 401
    second_code = auth.setup_code()
    assert second_code not in (None, first_code)
    assert second_code in caplog.text


def test_wrong_setup_codes_are_counted(auth):
    code = auth.setup_code()
    for _attempt in range(5):
        assert status_of(lambda: auth.create_first_admin("wrong-code", ADMIN, TEST_PASSWORD, TEST_PASSWORD, "203.0.113.9")) == 401
    assert status_of(lambda: auth.create_first_admin(code, ADMIN, TEST_PASSWORD, TEST_PASSWORD, "203.0.113.9")) == 429
    assert auth.needs_setup()
    assert auth.create_first_admin(code, ADMIN, TEST_PASSWORD, TEST_PASSWORD, "198.51.100.4")


def test_a_right_code_with_a_bad_email_keeps_the_code(auth):
    code = auth.setup_code()
    assert status_of(lambda: auth.create_first_admin(code, "not-an-email", TEST_PASSWORD, TEST_PASSWORD)) == 400
    assert auth.create_first_admin(code, ADMIN, TEST_PASSWORD, TEST_PASSWORD)


@pytest.mark.parametrize("host", ["localhost:8095", "127.0.0.1:8095", "[::1]:8095", "10.1.2.3:8095", "mp3.localhost"])
def test_local_names_are_allowed_by_default(host):
    assert web.is_allowed_host(host, ())


@pytest.mark.parametrize("host", ["rebind.evil.example:8095", "localhost.evil.example", ""])
def test_other_names_are_refused_by_default(host):
    assert not web.is_allowed_host(host, ())


def test_allowed_hosts_replace_the_default_names(monkeypatch, tmp_path, settings, auth, jobs, worker, fake_youtube, database):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALLOWED_HOSTS", "MP3.example.com, other.example.com")
    assert load_settings().allowed_hosts == ("mp3.example.com", "other.example.com")
    client = app_for(replace(settings, allowed_hosts=("mp3.example.com",)), auth, jobs, worker, fake_youtube, database).test_client()
    assert client.get("/setup").status_code == 421
    assert client.get("/setup", base_url="https://mp3.example.com").status_code == 200


def test_the_starfire_mode_answers_on_any_host_name(settings, jobs, worker, fake_youtube, database):
    starfire = StarfireAuth("http://127.0.0.1:8090/api/auth/me", lambda request, timeout: pytest.fail("starfire was asked"))
    client = app_for(replace(settings, auth_mode="starfire"), starfire, jobs, worker, fake_youtube, database).test_client()
    assert client.get("/api/session", base_url="https://mp3.example.com").status_code == 200
