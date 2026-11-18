from dataclasses import replace

import pytest

from conftest import CLIENT_HEADERS, TEST_PASSWORD, set_up_admin
from spotmp3.config import ConfigError, load_settings
from spotmp3.web import create_app


def session_cookie(response) -> str:
    return next(value for value in response.headers.getlist("Set-Cookie") if value.startswith("spotmp3_session="))


def app_with(app_parts, secure_cookies: str):
    settings, auth, jobs, worker, fake_youtube, site_settings = app_parts
    application = create_app(replace(settings, secure_cookies=secure_cookies), auth, jobs, worker, fake_youtube, site_settings)
    application.testing = True
    return application


@pytest.fixture
def app_parts(settings, auth, jobs, worker, fake_youtube, database):
    from spotmp3.site_settings import SiteSettings
    return settings, auth, jobs, worker, fake_youtube, SiteSettings(database, settings)


def sign_in(client, base_url: str):
    return client.post("/api/signin", json={"email": "admin@example.com", "password": TEST_PASSWORD}, headers=CLIENT_HEADERS,
                       base_url=base_url)


def test_secure_cookies_default_to_auto(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SECURE_COOKIES", raising=False)
    assert load_settings().secure_cookies == "auto"


def test_a_bad_secure_cookies_value_is_refused(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SECURE_COOKIES", "maybe")
    with pytest.raises(ConfigError, match="SECURE_COOKIES"):
        load_settings()


@pytest.mark.parametrize("value, meaning", [("1", "true"), ("yes", "true"), ("on", "true"), ("TRUE", "true"),
                                            ("0", "false"), ("no", "false"), ("off", "false"), ("False", "false"),
                                            ("auto", "auto")])
def test_secure_cookies_accepts_the_old_spellings(monkeypatch, tmp_path, value, meaning):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SECURE_COOKIES", value)
    assert load_settings().secure_cookies == meaning


def test_auto_is_secure_everywhere_but_plain_http_on_localhost(app_parts):
    application = app_with(app_parts, "auto")
    local = set_up_admin(application.test_client())
    assert "Secure" not in session_cookie(local)
    assert "Secure" in session_cookie(sign_in(application.test_client(), "http://192.0.2.1:8095"))
    assert "Secure" in session_cookie(sign_in(application.test_client(), "https://192.0.2.1:8095"))


@pytest.mark.parametrize("choice, secure", [("true", True), ("false", False)])
def test_secure_cookies_can_be_forced(app_parts, choice, secure):
    application = app_with(app_parts, choice)
    set_up_admin(application.test_client())
    response = sign_in(application.test_client(), "http://192.0.2.1:8095")
    assert ("Secure" in session_cookie(response)) is secure
