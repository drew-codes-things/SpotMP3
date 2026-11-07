import os

import pytest

from spotmp3.config import ConfigError, load_settings, read_env_file

NAMES = ("PORT", "AUTH_MODE", "PUBLIC_URL", "DATA_DIR", "RETENTION_HOURS")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    yield
    for name in NAMES:
        os.environ.pop(name, None)


def test_env_file_fills_settings_without_overriding_real_variables(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text('# comment\nPORT=9000\nPUBLIC_URL="https://spotmp3.example.com/"\nRETENTION_HOURS=6\n')
    monkeypatch.setenv("RETENTION_HOURS", "48")
    settings = load_settings()
    assert settings.port == 9000
    assert settings.retention_hours == 48
    assert settings.public_url == "https://spotmp3.example.com/"
    assert settings.ytdlp_auto_update is True


def test_bad_values_are_reported(tmp_path):
    (tmp_path / ".env").write_text("PORT=abc\n")
    with pytest.raises(ConfigError, match="PORT must be a whole number"):
        load_settings()


def test_bad_lines_and_modes_are_reported(monkeypatch, tmp_path):
    (tmp_path / "broken.env").write_text("just words\n")
    with pytest.raises(ConfigError, match="NAME=value"):
        read_env_file(tmp_path / "broken.env")
    monkeypatch.setenv("AUTH_MODE", "open")
    with pytest.raises(ConfigError, match="AUTH_MODE"):
        load_settings()
