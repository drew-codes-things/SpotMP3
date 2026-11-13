import importlib
import importlib.metadata
import logging
import os
import subprocess
import sys

PACKAGE_SPEC = "yt-dlp[default]"
DISTRIBUTION = "yt-dlp"
UPDATE_TIMEOUT_SECONDS = 180
ALREADY_UPDATED_FLAG = "SPOTMP3_YTDLP_UPDATED"
MAX_ERROR_LENGTH = 300

log = logging.getLogger("spotmp3.ytdlp")


def installed_version() -> str | None:
    importlib.invalidate_caches()
    try:
        return importlib.metadata.version(DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return None


def update_ytdlp(run=subprocess.run) -> tuple[str | None, str | None]:
    before = installed_version()
    command = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", PACKAGE_SPEC]
    try:
        result = run(command, capture_output=True, text=True, timeout=UPDATE_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("could not update yt-dlp (%s), keeping %s", error, before)
        return before, before
    if result.returncode != 0:
        log.warning("could not update yt-dlp (%s), keeping %s", (result.stderr or "").strip()[-MAX_ERROR_LENGTH:], before)
        return before, before
    return before, installed_version()


def update_and_restart_if_needed(enabled: bool, environ=os.environ, execv=os.execv, update=update_ytdlp) -> bool:
    if not enabled or environ.get(ALREADY_UPDATED_FLAG):
        log.info("yt-dlp %s is installed (no update at this start)", installed_version())
        return False
    before, after = update()
    if before == after:
        log.info("yt-dlp %s is the newest version", after)
        return False
    log.info("yt-dlp updated from %s to %s, restarting to load it", before, after)
    environ[ALREADY_UPDATED_FLAG] = "1"
    execv(sys.executable, [sys.executable, "-m", "spotmp3", *sys.argv[1:]])
    return True
