import os
from dataclasses import dataclass
from pathlib import Path

AUTH_MODES = ("builtin", "starfire")
ENV_FILE = Path(".env")


class ConfigError(ValueError):
    pass


def _text(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


def _number(name: str, default: int, minimum: int) -> int:
    raw = _text(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from error
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


def _flag(name: str, default: bool) -> bool:
    return _text(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    bind_host: str = "127.0.0.1"
    port: int = 8095
    auth_mode: str = "builtin"
    starfire_me_url: str = "http://127.0.0.1:8090/api/auth/me"
    starfire_signin_path: str = "/signin/"
    secure_cookies: bool = False
    spotify_client_id: str = ""
    public_url: str = ""
    retention_hours: int = 24
    storage_limit_mb: int = 2048
    min_free_mb: int = 500
    max_tracks_per_job: int = 500
    max_open_jobs_per_user: int = 5

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "spotmp3.db"

    @property
    def spotify_redirect_uri(self) -> str:
        return f"{self.public_url.rstrip('/')}/spotify/callback" if self.public_url else ""


def read_env_file(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not name.strip():
            raise ConfigError(f"{path}:{number} should look like NAME=value")
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def load_settings() -> Settings:
    read_env_file()
    auth_mode = _text("AUTH_MODE", "builtin").lower()
    if auth_mode not in AUTH_MODES:
        raise ConfigError(f"AUTH_MODE must be one of {', '.join(AUTH_MODES)}, got {auth_mode!r}")
    return Settings(
        data_dir=Path(_text("DATA_DIR", "./data")).resolve(),
        bind_host=_text("BIND_HOST", "127.0.0.1"),
        port=_number("PORT", 8095, 1),
        auth_mode=auth_mode,
        starfire_me_url=_text("STARFIRE_ME_URL", "http://127.0.0.1:8090/api/auth/me"),
        starfire_signin_path=_text("STARFIRE_SIGNIN_PATH", "/signin/"),
        secure_cookies=_flag("SECURE_COOKIES", False),
        spotify_client_id=_text("SPOTIFY_CLIENT_ID", ""),
        public_url=_text("PUBLIC_URL", ""),
        retention_hours=_number("RETENTION_HOURS", 24, 1),
        storage_limit_mb=_number("STORAGE_LIMIT_MB", 2048, 100),
        min_free_mb=_number("MIN_FREE_MB", 500, 50),
        max_tracks_per_job=_number("MAX_TRACKS_PER_JOB", 500, 1),
        max_open_jobs_per_user=_number("MAX_OPEN_JOBS_PER_USER", 5, 1),
    )
