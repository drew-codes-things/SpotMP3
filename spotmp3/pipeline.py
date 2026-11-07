import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audio import Tags, download_cover, encode_mp3
from .spotify import SpotifyLinkError, track_cover
from .tracks import Track
from .youtube import Match, YouTube

OUTPUT_NAME = "output.mp3"

log = logging.getLogger("spotmp3.pipeline")


class ConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Converted:
    match: Match
    mp3_path: Path


@dataclass
class Pipeline:
    youtube: YouTube
    cover_lookup: Callable[[str], str | None] = track_cover
    cover_download: Callable[[str | None, Path], Path | None] = download_cover
    encoder: Callable[..., None] = encode_mp3

    def _cover_url(self, track: Track) -> str | None:
        if track.cover_url or not track.spotify_id:
            return track.cover_url
        try:
            return self.cover_lookup(track.spotify_id)
        except (SpotifyLinkError, OSError) as error:
            log.warning("no cover for Spotify track %s: %s", track.spotify_id, error)
            return None

    def _cover(self, track: Track, folder: Path) -> Path | None:
        url = self._cover_url(track)
        try:
            return self.cover_download(url, folder)
        except OSError as error:
            log.warning("cover download failed for %r: %s", track.title, error)
            return None

    def convert(self, track: Track, quality: str, folder: Path, on_match: Callable[[Match], None] | None = None) -> Converted:
        match = self.youtube.find_match(track)
        if match is None:
            raise ConversionError("no close enough match was found on YouTube")
        if on_match:
            on_match(match)
        source = self.youtube.download_audio(match, folder)
        cover = self._cover(track, folder)
        output = folder / OUTPUT_NAME
        tags = Tags.for_track(track, match.album, f"Source: {match.url}")
        self.encoder(source, output, quality, tags, cover, track.youtube_id is not None)
        return Converted(match, output)
