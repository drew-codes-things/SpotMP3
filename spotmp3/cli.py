import argparse
import logging
import shutil
import sys
import tempfile
from pathlib import Path

from . import __version__
from .audio import DEFAULT_QUALITY, QUALITIES, safe_file_name, unique_path
from .auth import BuiltinAuth, StarfireAuth
from .config import ConfigError, Settings, load_settings, ytdlp_auto_update_enabled
from .db import Database
from .jobs import JobStore
from .pipeline import ConversionError, Pipeline
from .site_settings import SiteSettings
from .sources import SourceError, resolve_any
from .worker import EXPECTED_FAILURES, Worker
from .youtube import YouTube
from .ytdlp_update import update_and_restart_if_needed

SERVER_THREADS = 8
CLI_TRACK_LIMIT = 500
REQUIRED_PROGRAMS = ("ffmpeg",)

log = logging.getLogger("spotmp3")


def check_programs() -> None:
    missing = [program for program in REQUIRED_PROGRAMS if shutil.which(program) is None]
    if missing:
        raise ConfigError(f"install {', '.join(missing)} first (it is needed to make MP3 files)")


def build_auth(settings: Settings, database: Database):
    if settings.auth_mode == "starfire":
        return StarfireAuth(settings.starfire_me_url)
    return BuiltinAuth(database)


def serve() -> None:
    from waitress import serve as waitress_serve

    from .web import create_app

    settings = load_settings()
    check_programs()
    database = Database(settings.database_path)
    youtube = YouTube()
    worker = Worker(settings, database, Pipeline(youtube))
    worker.start()
    app = create_app(settings, build_auth(settings, database), JobStore(database, settings), worker, youtube, SiteSettings(database, settings))
    log.info("SpotMP3 %s listening on http://%s:%s (%s accounts)", __version__, settings.bind_host, settings.port, settings.auth_mode)
    try:
        waitress_serve(app, host=settings.bind_host, port=settings.port, threads=SERVER_THREADS, ident="SpotMP3")
    finally:
        worker.stop()


def show(link: str) -> None:
    collection = resolve_any(link, YouTube(), CLI_TRACK_LIMIT)
    print(f"{collection.kind}: {collection.name} ({len(collection.tracks)} tracks{', list cut short' if collection.truncated else ''})")
    for number, track in enumerate(collection.tracks, start=1):
        seconds = track.duration_ms // 1000
        print(f"{number:>3}. {track.artist_line} - {track.title} [{seconds // 60}:{seconds % 60:02d}]")


def convert(link: str, quality: str, output: Path) -> int:
    check_programs()
    youtube = YouTube()
    pipeline = Pipeline(youtube)
    collection = resolve_any(link, youtube, CLI_TRACK_LIMIT)
    output.mkdir(parents=True, exist_ok=True)
    failures = 0
    for number, track in enumerate(collection.tracks, start=1):
        label = f"[{number}/{len(collection.tracks)}] {track.artist_line} - {track.title}"
        with tempfile.TemporaryDirectory(prefix="spotmp3-") as work:
            try:
                converted = pipeline.convert(track, quality, Path(work))
            except EXPECTED_FAILURES as error:
                failures += 1
                print(f"{label}: failed, {error}", file=sys.stderr)
                continue
            destination = unique_path(output, safe_file_name(track.artist_line, track.title))
            shutil.move(converted.mp3_path, destination)
        print(f"{label}: {destination} (from {converted.match.url})")
    return 1 if failures else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="spotmp3", description="Turn Spotify and YouTube links into tagged MP3 files.")
    parser.add_argument("--version", action="version", version=f"SpotMP3 {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="run the web app (the default)")
    show_parser = commands.add_parser("show", help="list the tracks behind a link")
    show_parser.add_argument("link")
    convert_parser = commands.add_parser("convert", help="convert a link to MP3 files without the web app")
    convert_parser.add_argument("link")
    convert_parser.add_argument("--quality", choices=sorted(QUALITIES), default=DEFAULT_QUALITY)
    convert_parser.add_argument("--out", type=Path, default=Path("."))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        update_and_restart_if_needed(ytdlp_auto_update_enabled())
        if args.command == "show":
            show(args.link)
            return 0
        if args.command == "convert":
            return convert(args.link, args.quality, args.out)
        serve()
        return 0
    except (ConfigError, SourceError, ConversionError) as error:
        print(f"spotmp3: {error}", file=sys.stderr)
        return 2
