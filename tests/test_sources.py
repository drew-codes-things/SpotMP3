import pytest

from spotmp3.sources import SourceError, resolve_any
from spotmp3.tracks import Collection, Track
from spotmp3.youtube import YouTubeError


class RecordingYouTube:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.fail = fail

    def _tracks(self, count):
        return [Track(title=f"V{number}", artists=("C",), duration_ms=1000, youtube_id="yybnK-DhphM") for number in range(count)]

    def video_collection(self, video_id):
        self.calls.append(("video", video_id))
        if self.fail:
            raise YouTubeError("Video unavailable")
        return Collection("video", "C - V0", self._tracks(1))

    def playlist_collection(self, playlist_id, limit):
        self.calls.append(("playlist", playlist_id, limit))
        return Collection("youtube playlist", "List", self._tracks(5))


@pytest.mark.parametrize("link", ["https://youtu.be/yybnK-DhphM?si=BXBowfUZfLXziybM", "https://www.youtube.com/watch?v=yybnK-DhphM"])
def test_both_youtube_video_links_go_to_the_same_video(link):
    youtube = RecordingYouTube()
    collection = resolve_any(link, youtube, 10, fetch=lambda url: pytest.fail("Spotify must not be asked"))
    assert youtube.calls == [("video", "yybnK-DhphM")]
    assert collection.kind == "video"


def test_youtube_playlists_are_cut_to_the_job_limit():
    youtube = RecordingYouTube()
    collection = resolve_any("https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI", youtube, 3)
    assert len(collection.tracks) == 3 and collection.truncated


def test_spotify_links_go_to_spotify():
    page = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"state":{"data":{"entity":{"name":"A","trackList":[{"title":"x","subtitle":"y","duration":5}]}}}}}}</script>'
    collection = resolve_any("https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa", RecordingYouTube(), 10, fetch=lambda url: page)
    assert collection.name == "A"


@pytest.mark.parametrize("link", ["https://example.com/song", "https://www.youtube.com/@channel", "hello", "https://open.spotify.com/artist/4m2880jivSbbyEGAKfITCa"])
def test_unsupported_links_give_a_clear_error(link):
    with pytest.raises(SourceError, match="Spotify|YouTube|supported"):
        resolve_any(link, RecordingYouTube(), 10, fetch=lambda url: "")


def test_youtube_errors_become_source_errors():
    with pytest.raises(SourceError, match="Video unavailable"):
        resolve_any("https://youtu.be/yybnK-DhphM", RecordingYouTube(fail=True), 10)
