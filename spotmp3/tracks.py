import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

SPOTIFY_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{22}$")
YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
COVER_HOST_SUFFIXES = (".scdn.co", ".spotifycdn.com", ".ytimg.com")
MAX_TEXT_LENGTH = 300
MAX_ARTISTS = 20
MAX_DURATION_MS = 3 * 60 * 60 * 1000


class TrackError(ValueError):
    pass


@dataclass(frozen=True)
class Track:
    title: str
    artists: tuple[str, ...]
    duration_ms: int
    spotify_id: str | None = None
    album: str | None = None
    track_number: int | None = None
    cover_url: str | None = None
    youtube_id: str | None = None

    @property
    def artist_line(self) -> str:
        return ", ".join(self.artists)

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "artists": list(self.artists),
            "durationMs": self.duration_ms,
            "spotifyId": self.spotify_id,
            "album": self.album,
            "trackNumber": self.track_number,
            "coverUrl": self.cover_url,
            "youtubeId": self.youtube_id,
        }


@dataclass
class Collection:
    kind: str
    name: str
    tracks: list[Track] = field(default_factory=list)
    truncated: bool = False


def is_safe_cover_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and any(host.endswith(suffix) for suffix in COVER_HOST_SUFFIXES)


def _clean_text(value, label: str, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            raise TrackError(f"{label} is missing")
        return None
    if not isinstance(value, str):
        raise TrackError(f"{label} must be text")
    text = " ".join(value.split())
    if len(text) > MAX_TEXT_LENGTH:
        raise TrackError(f"{label} is too long")
    if required and not text:
        raise TrackError(f"{label} is missing")
    return text or None


def track_from_json(data) -> Track:
    if not isinstance(data, dict):
        raise TrackError("each track must be an object")
    title = _clean_text(data.get("title"), "title", required=True)
    raw_artists = data.get("artists")
    if not isinstance(raw_artists, list) or not raw_artists or len(raw_artists) > MAX_ARTISTS:
        raise TrackError(f"track {title!r} needs between 1 and {MAX_ARTISTS} artists")
    artists = tuple(_clean_text(artist, "artist", required=True) for artist in raw_artists)
    duration = data.get("durationMs")
    if not isinstance(duration, int) or isinstance(duration, bool) or not 0 < duration <= MAX_DURATION_MS:
        raise TrackError(f"track {title!r} has an invalid length")
    spotify_id = data.get("spotifyId")
    if spotify_id is not None and not (isinstance(spotify_id, str) and SPOTIFY_ID_PATTERN.match(spotify_id)):
        raise TrackError(f"track {title!r} has an invalid Spotify id")
    number = data.get("trackNumber")
    if number is not None and not (isinstance(number, int) and not isinstance(number, bool) and 0 < number < 10000):
        raise TrackError(f"track {title!r} has an invalid track number")
    youtube_id = data.get("youtubeId")
    if youtube_id is not None and not (isinstance(youtube_id, str) and YOUTUBE_ID_PATTERN.match(youtube_id)):
        raise TrackError(f"track {title!r} has an invalid YouTube id")
    cover = data.get("coverUrl")
    return Track(
        title=title,
        artists=artists,
        duration_ms=duration,
        spotify_id=spotify_id,
        album=_clean_text(data.get("album"), "album", required=False),
        track_number=number,
        cover_url=cover if is_safe_cover_url(cover) else None,
        youtube_id=youtube_id,
    )
