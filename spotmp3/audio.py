import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .tracks import Track, is_safe_cover_url

QUALITIES: dict[str, tuple[str, list[str]]] = {
    "128": ("128 kbps", ["-b:a", "128k"]),
    "192": ("192 kbps", ["-b:a", "192k"]),
    "256": ("256 kbps", ["-b:a", "256k"]),
    "320": ("320 kbps", ["-b:a", "320k"]),
    "v0": ("VBR V0 (about 245 kbps)", ["-q:a", "0"]),
}
DEFAULT_QUALITY = "320"
ENCODE_TIMEOUT_SECONDS = 30 * 60
COVER_TIMEOUT_SECONDS = 15
MAX_COVER_BYTES = 5 * 1024 * 1024
MAX_FILE_NAME_LENGTH = 150
UNSAFE_FILE_CHARACTERS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
COVER_SCALE = "scale=min(640\\,iw):-2"
VIDEO_FRAME_SQUARE_CROP = "crop=iw:min(ih\\,iw*9/16),crop=min(iw\\,ih):min(iw\\,ih),"


class AudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tags:
    title: str
    artist: str
    album: str | None = None
    track_number: int | None = None
    source_note: str | None = None

    @classmethod
    def for_track(cls, track: Track, album: str | None, source_note: str) -> "Tags":
        return cls(track.title, track.artist_line, track.album or album, track.track_number, source_note)


def quality_choices() -> list[tuple[str, str]]:
    return [(key, label) for key, (label, _) in QUALITIES.items()]


def encoder_arguments(quality: str) -> list[str]:
    if quality not in QUALITIES:
        raise AudioError(f"unknown quality {quality!r}")
    return QUALITIES[quality][1]


def safe_file_name(artist: str, title: str) -> str:
    stem = UNSAFE_FILE_CHARACTERS.sub("", f"{artist} - {title}")
    stem = " ".join(stem.split()).strip(" .") or "track"
    return f"{stem[:MAX_FILE_NAME_LENGTH].rstrip(' .')}.mp3"


def unique_path(folder: Path, file_name: str) -> Path:
    candidate = folder / file_name
    stem, suffix = candidate.stem, candidate.suffix
    copy_number = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({copy_number}){suffix}"
        copy_number += 1
    return candidate


def metadata_arguments(tags: Tags) -> list[str]:
    values = {"title": tags.title, "artist": tags.artist, "album": tags.album, "track": tags.track_number, "comment": tags.source_note}
    arguments = []
    for key, value in values.items():
        if value is not None and value != "":
            arguments += ["-metadata", f"{key}={value}"]
    return arguments


def ffmpeg_command(source: Path, destination: Path, quality: str, tags: Tags, cover: Path | None, cover_is_video_frame: bool = False) -> list[str]:
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source)]
    if cover:
        cover_filter = (VIDEO_FRAME_SQUARE_CROP if cover_is_video_frame else "") + COVER_SCALE
        command += ["-i", str(cover), "-map", "0:a:0", "-map", "1:v:0", "-c:v", "mjpeg", "-vf", cover_filter,
                    "-disposition:v:0", "attached_pic", "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        command += ["-map", "0:a:0"]
    command += ["-c:a", "libmp3lame", *encoder_arguments(quality), "-id3v2_version", "3", *metadata_arguments(tags), str(destination)]
    return command


def encode_mp3(source: Path, destination: Path, quality: str, tags: Tags, cover: Path | None, cover_is_video_frame: bool = False) -> None:
    command = ffmpeg_command(source, destination, quality, tags, cover, cover_is_video_frame)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=ENCODE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise AudioError("converting to MP3 took longer than 30 minutes") from error
    if result.returncode != 0 or not destination.is_file():
        raise AudioError(f"ffmpeg could not make the MP3: {result.stderr.strip()[-300:]}")


def download_cover(url: str | None, folder: Path) -> Path | None:
    if not is_safe_cover_url(url):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": "SpotMP3"})
    with urllib.request.urlopen(request, timeout=COVER_TIMEOUT_SECONDS) as response:
        data = response.read(MAX_COVER_BYTES + 1)
    if len(data) > MAX_COVER_BYTES or not data:
        return None
    path = folder / "cover.jpg"
    path.write_bytes(data)
    return path
