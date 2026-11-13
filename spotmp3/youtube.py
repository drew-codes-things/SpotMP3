from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

import yt_dlp

from .matching import Candidate, choose_best, duration_fits, music_result_plausible
from .tracks import YOUTUBE_ID_PATTERN, Collection, Track
from .youtube_links import canonical_url, clean_channel, split_video_title

MUSIC_SEARCH_URL = "https://music.youtube.com/search?q={query}#songs"
VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"
MUSIC_RESULTS_CHECKED = 3
VIDEO_RESULTS_CHECKED = 8
SOCKET_TIMEOUT_SECONDS = 30
MAX_SOURCE_SECONDS = 3 * 60 * 60
MAX_SOURCE_BYTES = 512 * 1024 * 1024
THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
UNAVAILABLE_TITLES = ("[private video]", "[deleted video]")
LIVE_STREAM_REFUSAL = "live streams cannot be converted"
TOO_LONG_REFUSAL = "the video is longer than 3 hours"
TOO_LARGE_REFUSAL = "the download is larger than 512 MB"

YdlFactory = Callable[[dict], "yt_dlp.YoutubeDL"]


class YouTubeError(RuntimeError):
    pass


class SourceTooLarge(yt_dlp.utils.DownloadCancelled):
    msg = TOO_LARGE_REFUSAL


def stop_past_size_cap(progress: dict) -> None:
    if (progress.get("downloaded_bytes") or 0) > MAX_SOURCE_BYTES:
        raise SourceTooLarge()


@dataclass(frozen=True)
class Match:
    video_id: str
    title: str
    channel: str
    duration_seconds: float
    album: str | None = None

    @property
    def url(self) -> str:
        return VIDEO_URL.format(video_id=self.video_id)


def _base_options() -> dict:
    return {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": SOCKET_TIMEOUT_SECONDS, "noplaylist": True}


def source_refusal(info: dict, *, incomplete: bool = False) -> str | None:
    if info.get("is_live"):
        return LIVE_STREAM_REFUSAL
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > MAX_SOURCE_SECONDS:
        return TOO_LONG_REFUSAL
    return None


def thumbnail_url(video_id: str) -> str:
    return THUMBNAIL_URL.format(video_id=video_id)


def _artist_and_title(info: dict) -> tuple[str, str]:
    track_name = info.get("track")
    artist_name = info.get("artist") or info.get("creator")
    if isinstance(track_name, str) and track_name.strip() and isinstance(artist_name, str) and artist_name.strip():
        return artist_name.strip(), track_name.strip()
    return split_video_title(info.get("title") or "", info.get("channel") or info.get("uploader") or "")


def track_from_video(info: dict, album: str | None = None, track_number: int | None = None) -> Track | None:
    video_id = info.get("id")
    duration = info.get("duration")
    title = info.get("title") or ""
    if not isinstance(video_id, str) or not YOUTUBE_ID_PATTERN.match(video_id):
        return None
    if not duration or title.strip().lower() in UNAVAILABLE_TITLES:
        return None
    artist, name = _artist_and_title(info)
    return Track(
        title=name,
        artists=(artist,),
        duration_ms=int(float(duration) * 1000),
        album=info.get("album") or album,
        track_number=track_number,
        cover_url=thumbnail_url(video_id),
        youtube_id=video_id,
    )


class YouTube:
    def __init__(self, ydl_factory: YdlFactory = yt_dlp.YoutubeDL):
        self._factory = ydl_factory

    def _extract(self, url: str, options: dict, download: bool = False) -> dict:
        try:
            with self._factory({**_base_options(), **options}) as ydl:
                info = ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as error:
            raise YouTubeError(str(error).replace("ERROR: ", "")[:300]) from error
        except SourceTooLarge as error:
            raise YouTubeError(TOO_LARGE_REFUSAL) from error
        if not isinstance(info, dict):
            raise YouTubeError(f"YouTube returned nothing for {url}")
        return info

    def _search(self, url: str, limit: int, from_music: bool) -> list[Candidate]:
        info = self._extract(url, {"extract_flat": "in_playlist", "playlistend": limit})
        candidates = []
        for entry in (info.get("entries") or [])[:limit]:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            candidates.append(Candidate(
                video_id=entry["id"],
                title=entry.get("title") or "",
                channel=entry.get("channel") or entry.get("uploader") or "",
                duration_seconds=entry.get("duration"),
                verified=bool(entry.get("channel_is_verified")),
                from_music_search=from_music,
            ))
        return candidates

    def search_music(self, query: str) -> list[Candidate]:
        return self._search(MUSIC_SEARCH_URL.format(query=quote_plus(query)), MUSIC_RESULTS_CHECKED, from_music=True)

    def search_videos(self, query: str) -> list[Candidate]:
        return self._search(f"ytsearch{VIDEO_RESULTS_CHECKED}:{query}", VIDEO_RESULTS_CHECKED, from_music=False)

    def details(self, video_id: str) -> dict:
        return self._extract(VIDEO_URL.format(video_id=video_id), {"skip_download": True})

    def video_collection(self, video_id: str) -> Collection:
        track = track_from_video(self.details(video_id))
        if track is None:
            raise YouTubeError("that YouTube video is private, removed or has no length")
        return Collection(kind="video", name=f"{track.artist_line} - {track.title}", tracks=[track])

    def playlist_collection(self, playlist_id: str, limit: int) -> Collection:
        info = self._extract(canonical_url("playlist", playlist_id), {"extract_flat": "in_playlist", "playlistend": limit + 1, "noplaylist": False})
        entries = [entry for entry in info.get("entries") or [] if isinstance(entry, dict)]
        tracks = [track for track in (track_from_video(entry) for entry in entries[:limit]) if track is not None]
        name = info.get("title") or "YouTube playlist"
        return Collection(kind="youtube playlist", name=clean_channel(name) if name.endswith(" - Topic") else name,
                          tracks=tracks, truncated=len(entries) > limit)

    def find_match(self, track: Track) -> Match | None:
        if track.youtube_id:
            return Match(track.youtube_id, track.title, track.artist_line, track.duration_ms / 1000, track.album)
        query = f"{track.artist_line} {track.title}"
        for candidate in self.search_music(query):
            if not music_result_plausible(track, candidate):
                continue
            info = self.details(candidate.video_id)
            if duration_fits(track, info.get("duration")):
                return Match(candidate.video_id, info.get("title") or candidate.title, info.get("channel") or candidate.channel,
                             float(info["duration"]), info.get("album"))
        best = choose_best(track, self.search_videos(f"{track.artist_line} - {track.title}"))
        if best is None:
            return None
        return Match(best.video_id, best.title, best.channel, float(best.duration_seconds or 0))

    def download_audio(self, match: Match, folder: Path) -> Path:
        if match.duration_seconds > MAX_SOURCE_SECONDS:
            raise YouTubeError(TOO_LONG_REFUSAL)
        options = {"format": "bestaudio/best", "outtmpl": str(folder / "source.%(ext)s"), "match_filter": source_refusal,
                   "max_filesize": MAX_SOURCE_BYTES, "progress_hooks": [stop_past_size_cap]}
        info = self._extract(match.url, options, download=True)
        refusal = source_refusal(info)
        if refusal:
            raise YouTubeError(refusal)
        downloads = info.get("requested_downloads") or []
        path = Path(downloads[0]["filepath"]) if downloads and downloads[0].get("filepath") else None
        if path is None or not path.is_file():
            found = sorted(folder.glob("source.*"))
            path = found[0] if found else None
        if path is None:
            raise YouTubeError("yt-dlp finished without writing an audio file")
        return path
