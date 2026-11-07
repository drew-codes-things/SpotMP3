import subprocess
import sys

from spotmp3 import ytdlp_update
from spotmp3.ytdlp_update import ALREADY_UPDATED_FLAG, update_and_restart_if_needed, update_ytdlp


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)


def test_a_newer_yt_dlp_restarts_the_app_once():
    environ, execv = {}, Recorder()
    restarted = update_and_restart_if_needed(True, environ, execv, update=lambda: ("2026.07.04", "2026.10.26"))
    assert restarted and environ[ALREADY_UPDATED_FLAG] == "1"
    executable, arguments = execv.calls[0]
    assert executable == sys.executable and arguments[:3] == [sys.executable, "-m", "spotmp3"]
    assert update_and_restart_if_needed(True, environ, execv, update=lambda: ("a", "b")) is False
    assert len(execv.calls) == 1


def test_no_restart_when_already_current_or_turned_off():
    execv = Recorder()
    assert update_and_restart_if_needed(True, {}, execv, update=lambda: ("2026.10.26", "2026.10.26")) is False
    assert update_and_restart_if_needed(False, {}, execv, update=lambda: ("a", "b")) is False
    assert execv.calls == []


def test_pip_failure_keeps_the_installed_version(monkeypatch):
    monkeypatch.setattr(ytdlp_update, "installed_version", lambda: "2026.10.26")

    def failing_pip(command, **options):
        assert command[1:4] == ["-m", "pip", "install"] and command[-1] == "yt-dlp[default]"
        return subprocess.CompletedProcess(command, 1, "", "ERROR: Could not install packages: Permission denied")

    def missing_pip(command, **options):
        raise OSError("no pip")

    assert update_ytdlp(failing_pip) == ("2026.10.26", "2026.10.26")
    assert update_ytdlp(missing_pip) == ("2026.10.26", "2026.10.26")


def test_installed_version_reads_the_real_package():
    assert ytdlp_update.installed_version().startswith("20")
