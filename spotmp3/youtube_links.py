import re
from urllib.parse import parse_qs, urlparse

from .tracks import YOUTUBE_ID_PATTERN

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
PATH_VIDEO_PREFIXES = ("shorts", "live", "embed", "v")
PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
CHANNEL_NOISE = re.compile(r"\s*(-\s*topic|vevo|official)$", re.I)
TITLE_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|mv|m/v|music video)\b[^\)\]]*[\)\]]",
    re.I,
)
ARTIST_SEPARATOR = re.compile(r"\s+[-–]\s+")

VIDEO_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={playlist_id}"


class YouTubeLinkError(ValueError):
    pass


def is_youtube_link(text: str) -> bool:
    host = (urlparse((text or "").strip()).hostname or "").lower()
    return host in YOUTUBE_HOSTS or host in SHORT_HOSTS


def _video(video_id: str) -> tuple[str, str]:
    if not YOUTUBE_ID_PATTERN.match(video_id or ""):
        raise YouTubeLinkError("that YouTube link has an invalid video id")
    return "video", video_id


def parse_youtube_link(text: str) -> tuple[str, str]:
    parsed = urlparse((text or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https"):
        raise YouTubeLinkError("paste a full YouTube link starting with https://")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if host in SHORT_HOSTS:
        return _video(segments[0] if segments else "")
    if host not in YOUTUBE_HOSTS:
        raise YouTubeLinkError("that is not a YouTube link")
    query = parse_qs(parsed.query)
    if segments[:1] == ["watch"]:
        return _video((query.get("v") or [""])[0])
    if len(segments) >= 2 and segments[0] in PATH_VIDEO_PREFIXES:
        return _video(segments[1])
    if segments[:1] == ["playlist"]:
        playlist_id = (query.get("list") or [""])[0]
        if not PLAYLIST_ID_PATTERN.match(playlist_id):
            raise YouTubeLinkError("that YouTube playlist link has an invalid id")
        return "playlist", playlist_id
    raise YouTubeLinkError("only YouTube video and playlist links are supported")


def canonical_url(kind: str, identifier: str) -> str:
    return VIDEO_WATCH_URL.format(video_id=identifier) if kind == "video" else PLAYLIST_URL.format(playlist_id=identifier)


def clean_channel(channel: str) -> str:
    return CHANNEL_NOISE.sub("", (channel or "").strip()).strip() or "Unknown artist"


def split_video_title(title: str, channel: str) -> tuple[str, str]:
    cleaned = " ".join(TITLE_NOISE.sub("", title or "").split())
    parts = ARTIST_SEPARATOR.split(cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].strip(), parts[1].strip()
    return clean_channel(channel), cleaned or "Unknown title"
