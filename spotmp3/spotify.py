import json
import re
import urllib.request
from typing import Callable
from urllib.parse import urlparse

from .tracks import SPOTIFY_ID_PATTERN, Collection, Track, is_safe_cover_url

EMBED_URL = "https://open.spotify.com/embed/{kind}/{spotify_id}"
EMBED_PLAYLIST_LIMIT = 100
FETCH_TIMEOUT_SECONDS = 15
MAX_EMBED_BYTES = 5 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SUPPORTED_KINDS = ("track", "album", "playlist")
NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
URI_PATTERN = re.compile(r"^spotify:(track|album|playlist):([A-Za-z0-9]{22})$")
LOCALE_SEGMENT = re.compile(r"^intl-[a-z]{2}(-[a-z]{2})?$", re.I)

Fetcher = Callable[[str], str]


class SpotifyLinkError(ValueError):
    pass


def parse_spotify_link(text: str) -> tuple[str, str]:
    value = (text or "").strip()
    uri = URI_PATTERN.match(value)
    if uri:
        return uri.group(1), uri.group(2)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or parsed.hostname != "open.spotify.com":
        raise SpotifyLinkError("paste a link from open.spotify.com (a track, album or playlist)")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and LOCALE_SEGMENT.match(segments[0]):
        segments = segments[1:]
    if segments and segments[0] == "embed":
        segments = segments[1:]
    if len(segments) < 2 or segments[0] not in SUPPORTED_KINDS:
        raise SpotifyLinkError("only track, album and playlist links are supported")
    kind, spotify_id = segments[0], segments[1]
    if not SPOTIFY_ID_PATTERN.match(spotify_id):
        raise SpotifyLinkError("that Spotify link has an invalid id")
    return kind, spotify_id


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_EMBED_BYTES + 1)
    if len(body) > MAX_EMBED_BYTES:
        raise SpotifyLinkError("Spotify sent an unexpectedly large page")
    return body.decode("utf-8", errors="replace")


def _entity(html: str) -> dict:
    match = NEXT_DATA_PATTERN.search(html)
    if not match:
        raise SpotifyLinkError("Spotify's page did not include the track list (it may be private or removed)")
    try:
        data = json.loads(match.group(1))
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (ValueError, KeyError, TypeError) as error:
        raise SpotifyLinkError("Spotify's page had an unexpected layout") from error
    if not isinstance(entity, dict):
        raise SpotifyLinkError("Spotify's page had an unexpected layout")
    return entity


def _largest_image(entity: dict) -> str | None:
    images = (entity.get("visualIdentity") or {}).get("image") or []
    sized = [image for image in images if isinstance(image, dict) and is_safe_cover_url(image.get("url"))]
    if not sized:
        return None
    return max(sized, key=lambda image: image.get("maxWidth") or 0)["url"]


def _id_from_uri(uri) -> str | None:
    if not isinstance(uri, str):
        return None
    candidate = uri.rsplit(":", 1)[-1]
    return candidate if SPOTIFY_ID_PATTERN.match(candidate) else None


def _split_artists(subtitle) -> tuple[str, ...]:
    if not isinstance(subtitle, str) or not subtitle.strip():
        return ("Unknown artist",)
    names = tuple(part.strip() for part in subtitle.replace(" ", " ").split(",") if part.strip())
    return names or ("Unknown artist",)


def _single_track(entity: dict) -> Collection:
    artists = tuple(artist["name"] for artist in entity.get("artists") or [] if isinstance(artist, dict) and artist.get("name"))
    track = Track(
        title=entity.get("title") or entity.get("name") or "Unknown title",
        artists=artists or ("Unknown artist",),
        duration_ms=int(entity.get("duration") or 0),
        spotify_id=_id_from_uri(entity.get("uri")),
        cover_url=_largest_image(entity),
    )
    return Collection(kind="track", name=f"{track.artist_line} - {track.title}", tracks=[track])


def _track_list(entity: dict, kind: str) -> Collection:
    album_name = entity.get("name") if kind == "album" else None
    cover = _largest_image(entity) if kind == "album" else None
    tracks = []
    for position, item in enumerate(entity.get("trackList") or [], start=1):
        if not isinstance(item, dict) or not item.get("title") or not item.get("duration"):
            continue
        tracks.append(Track(
            title=item["title"],
            artists=_split_artists(item.get("subtitle")),
            duration_ms=int(item["duration"]),
            spotify_id=_id_from_uri(item.get("uri")),
            album=album_name,
            track_number=position if kind == "album" else None,
            cover_url=cover,
        ))
    truncated = kind == "playlist" and len(tracks) >= EMBED_PLAYLIST_LIMIT
    return Collection(kind=kind, name=entity.get("name") or kind.title(), tracks=tracks, truncated=truncated)


def parse_embed(html: str, kind: str) -> Collection:
    entity = _entity(html)
    if kind == "track":
        return _single_track(entity)
    return _track_list(entity, kind)


def resolve_link(text: str, fetch: Fetcher = fetch_text) -> Collection:
    kind, spotify_id = parse_spotify_link(text)
    collection = parse_embed(fetch(EMBED_URL.format(kind=kind, spotify_id=spotify_id)), kind)
    if not collection.tracks:
        raise SpotifyLinkError("no playable tracks were found at that link")
    return collection


def track_cover(spotify_id: str, fetch: Fetcher = fetch_text) -> str | None:
    if not SPOTIFY_ID_PATTERN.match(spotify_id or ""):
        return None
    return _largest_image(_entity(fetch(EMBED_URL.format(kind="track", spotify_id=spotify_id))))
