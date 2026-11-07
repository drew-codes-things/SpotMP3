import json
import subprocess

import pytest

from conftest import make_tone
from spotmp3.audio import AudioError, Tags, encode_mp3, encoder_arguments, ffmpeg_command, safe_file_name


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def make_picture(path, size):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=red:s={size}", "-frames:v", "1", str(path)], check=True)
    return path


def test_file_names_are_safe():
    assert safe_file_name("AC/DC", 'What? "Yes": <no>') == "ACDC - What Yes no.mp3"
    assert safe_file_name("", "") == "-.mp3"
    assert len(safe_file_name("a" * 400, "b")) <= 154


def test_unknown_quality_is_refused():
    with pytest.raises(AudioError):
        encoder_arguments("999")


def test_command_has_no_cover_mapping_without_a_cover(tmp_path):
    command = ffmpeg_command(tmp_path / "in.opus", tmp_path / "out.mp3", "192", Tags("T", "A"), None)
    assert "attached_pic" not in command and "192k" in command


@pytest.mark.parametrize("quality, expected_kbps", [("128", 128), ("320", 320)])
def test_real_encode_has_bitrate_tags_and_square_cover(tmp_path, quality, expected_kbps):
    source = make_tone(tmp_path / "in.opus", seconds=3)
    cover = make_picture(tmp_path / "cover.jpg", "480x360")
    output = tmp_path / "out.mp3"
    encode_mp3(source, output, quality, Tags("Title", "Artist", "Album", 4, "Source: x"), cover, cover_is_video_frame=True)
    info = probe(output)
    audio = next(stream for stream in info["streams"] if stream["codec_type"] == "audio")
    picture = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
    assert audio["codec_name"] == "mp3" and int(audio["bit_rate"]) == expected_kbps * 1000
    assert (picture["width"], picture["height"]) == (270, 270)
    assert picture["disposition"]["attached_pic"] == 1
    tags = info["format"]["tags"]
    assert (tags["title"], tags["artist"], tags["album"], tags["track"]) == ("Title", "Artist", "Album", "4")


def test_spotify_cover_keeps_its_shape(tmp_path):
    source = make_tone(tmp_path / "in.opus")
    cover = make_picture(tmp_path / "cover.jpg", "300x300")
    output = tmp_path / "out.mp3"
    encode_mp3(source, output, "v0", Tags("T", "A"), cover)
    picture = next(stream for stream in probe(output)["streams"] if stream["codec_type"] == "video")
    assert (picture["width"], picture["height"]) == (300, 300)


def test_broken_source_reports_ffmpeg_error(tmp_path):
    source = tmp_path / "broken.opus"
    source.write_bytes(b"not audio")
    with pytest.raises(AudioError, match="ffmpeg could not make the MP3"):
        encode_mp3(source, tmp_path / "out.mp3", "128", Tags("T", "A"), None)
