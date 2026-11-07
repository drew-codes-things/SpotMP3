import re
from urllib.parse import urlparse

from .config import Settings
from .db import Database

SPOTIFY_CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{16,64}$")
MAX_PUBLIC_URL_LENGTH = 300
CALLBACK_PATH = "/spotify/callback"
KEYS = ("spotify_client_id", "public_url")


class SiteSettingsError(ValueError):
    pass


def clean_client_id(value) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if text and not SPOTIFY_CLIENT_ID_PATTERN.match(text):
        raise SiteSettingsError("that does not look like a Spotify Client ID (letters and numbers only, copied from the app's Settings page)")
    return text


def clean_public_url(value) -> str:
    text = value.strip().rstrip("/") if isinstance(value, str) else ""
    if not text:
        return ""
    parsed = urlparse(text)
    if len(text) > MAX_PUBLIC_URL_LENGTH or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SiteSettingsError("the public address must start with https:// (or http://) followed by the site's name")
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SiteSettingsError("the public address is only the site's address, for example https://mp3.example.com")
    return text


class SiteSettings:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def _stored(self) -> dict[str, str]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def spotify_client_id(self) -> str:
        return self._stored().get("spotify_client_id") or self.settings.spotify_client_id

    def public_url(self) -> str:
        return self._stored().get("public_url") or self.settings.public_url.rstrip("/")

    def redirect_uri(self, request_root: str) -> str:
        base = self.public_url() or request_root.rstrip("/")
        return f"{base}{CALLBACK_PATH}"

    def update(self, spotify_client_id, public_url) -> None:
        values = {"spotify_client_id": clean_client_id(spotify_client_id), "public_url": clean_public_url(public_url)}
        with self.database.connect() as connection:
            for key, value in values.items():
                if value:
                    connection.execute("INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
                else:
                    connection.execute("DELETE FROM app_settings WHERE key = ?", (key,))

    def to_json(self, request_root: str) -> dict:
        stored = self._stored()
        return {
            "spotifyClientId": stored.get("spotify_client_id", ""),
            "publicUrl": stored.get("public_url", ""),
            "spotifyClientIdFromServer": self.settings.spotify_client_id,
            "publicUrlFromServer": self.settings.public_url.rstrip("/"),
            "redirectUri": self.redirect_uri(request_root),
        }
