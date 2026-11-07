import pytest

from conftest import CLIENT_HEADERS, TEST_PASSWORD, set_up_admin
from spotmp3.site_settings import SiteSettings, SiteSettingsError

CLIENT_ID = "0123456789abcdef0123456789abcdef"


def test_saved_values_win_over_the_server_file_and_clearing_falls_back(database, settings):
    site = SiteSettings(database, settings.__class__(**{**settings.__dict__, "spotify_client_id": "fromtheenvfile123456", "public_url": "https://env.example.com/"}))
    assert site.spotify_client_id() == "fromtheenvfile123456"
    assert site.redirect_uri("http://127.0.0.1:8095/") == "https://env.example.com/spotify/callback"
    site.update(f"  {CLIENT_ID} ", "https://mp3.example.com/")
    assert site.spotify_client_id() == CLIENT_ID
    assert site.redirect_uri("http://ignored/") == "https://mp3.example.com/spotify/callback"
    site.update("", "")
    assert site.spotify_client_id() == "fromtheenvfile123456"


def test_without_any_public_address_the_page_address_is_used(database, settings):
    assert SiteSettings(database, settings).redirect_uri("http://192.168.1.5:8095/") == "http://192.168.1.5:8095/spotify/callback"


@pytest.mark.parametrize("client_id, public_url", [
    ("not valid!", ""),
    ("short", ""),
    ("", "ftp://mp3.example.com"),
    ("", "https://mp3.example.com/some/path"),
    ("", "https://mp3.example.com/?x=1"),
    ("", "mp3.example.com"),
])
def test_bad_values_are_refused(database, settings, client_id, public_url):
    with pytest.raises(SiteSettingsError):
        SiteSettings(database, settings).update(client_id, public_url)


def test_admin_edits_settings_on_the_site(client):
    set_up_admin(client)
    before = client.get("/api/settings").get_json()
    assert before["spotifyClientId"] == "" and before["redirectUri"] == "http://localhost/spotify/callback"
    saved = client.put("/api/settings", json={"spotifyClientId": CLIENT_ID, "publicUrl": "https://mp3.example.com"}, headers=CLIENT_HEADERS)
    assert saved.status_code == 200 and saved.get_json()["redirectUri"] == "https://mp3.example.com/spotify/callback"
    config = client.get("/api/config").get_json()
    assert (config["spotifyClientId"], config["spotifyRedirectUri"], config["canManageSettings"]) == (
        CLIENT_ID, "https://mp3.example.com/spotify/callback", True)
    refused = client.put("/api/settings", json={"spotifyClientId": "bad id!", "publicUrl": ""}, headers=CLIENT_HEADERS)
    assert refused.status_code == 400 and "Client ID" in refused.get_json()["error"]


def test_only_admins_can_see_or_change_settings(client, app):
    set_up_admin(client)
    client.post("/api/accounts", json={"email": "friend@example.com", "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    friend = app.test_client()
    friend.post("/api/signin", json={"email": "friend@example.com", "password": TEST_PASSWORD}, headers=CLIENT_HEADERS)
    assert friend.get("/api/settings").status_code == 403
    assert friend.put("/api/settings", json={"spotifyClientId": CLIENT_ID}, headers=CLIENT_HEADERS).status_code == 403
    assert friend.get("/api/config").get_json()["canManageSettings"] is False
    assert client.put("/api/settings", json={"spotifyClientId": CLIENT_ID}).status_code == 403
