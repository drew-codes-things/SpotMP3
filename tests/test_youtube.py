import pytest

from spotmp3.youtube import MAX_SOURCE_SECONDS, Match, YouTube, YouTubeError

VIDEO_ID = "abcdefghijk"


class FilterHonouringDownloader:
    def __init__(self, options, video_info):
        self.options = options
        self.video_info = video_info

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        info = dict(self.video_info)
        match_filter = self.options.get("match_filter")
        refused = match_filter(info, incomplete=False) if match_filter else None
        if download and refused is None:
            path = self.options["outtmpl"].replace("%(ext)s", "webm")
            with open(path, "wb") as handle:
                handle.write(b"audio")
            info["requested_downloads"] = [{"filepath": path}]
        return info


def youtube_serving(video_info):
    return YouTube(lambda options: FilterHonouringDownloader(options, video_info))


def claimed_short_match():
    return Match(VIDEO_ID, "Song", "Channel", 180.0)


def test_a_normal_video_is_downloaded(tmp_path):
    path = youtube_serving({"id": VIDEO_ID, "duration": 181, "is_live": False}).download_audio(claimed_short_match(), tmp_path)
    assert path.read_bytes() == b"audio"


def test_a_live_stream_is_refused_before_it_downloads(tmp_path):
    youtube = youtube_serving({"id": VIDEO_ID, "duration": None, "is_live": True})
    with pytest.raises(YouTubeError, match="live"):
        youtube.download_audio(claimed_short_match(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_video_longer_than_the_claimed_length_allows_is_refused(tmp_path):
    youtube = youtube_serving({"id": VIDEO_ID, "duration": MAX_SOURCE_SECONDS + 60, "is_live": False})
    with pytest.raises(YouTubeError, match="longer than 3 hours"):
        youtube.download_audio(claimed_short_match(), tmp_path)
    assert list(tmp_path.iterdir()) == []
