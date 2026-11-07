from .spotify import Fetcher, SpotifyLinkError, fetch_text, resolve_link as resolve_spotify_link
from .tracks import Collection
from .youtube import YouTube, YouTubeError
from .youtube_links import YouTubeLinkError, is_youtube_link, parse_youtube_link


UNSUPPORTED_LINK = "paste a Spotify link (track, album or playlist) or a YouTube link (video or playlist)"


class SourceError(ValueError):
    pass


def _looks_like_spotify(text: str) -> bool:
    value = (text or "").strip().lower()
    return value.startswith("spotify:") or "open.spotify.com" in value


def resolve_any(text: str, youtube: YouTube, track_limit: int, fetch: Fetcher = fetch_text) -> Collection:
    try:
        if is_youtube_link(text):
            kind, identifier = parse_youtube_link(text)
            collection = youtube.video_collection(identifier) if kind == "video" else youtube.playlist_collection(identifier, track_limit)
        elif _looks_like_spotify(text):
            collection = resolve_spotify_link(text, fetch)
        else:
            raise SourceError(UNSUPPORTED_LINK)
    except (SpotifyLinkError, YouTubeLinkError, YouTubeError) as error:
        raise SourceError(str(error)) from error
    if not collection.tracks:
        raise SourceError("no playable tracks were found at that link")
    if len(collection.tracks) > track_limit:
        collection.tracks = collection.tracks[:track_limit]
        collection.truncated = True
    return collection
