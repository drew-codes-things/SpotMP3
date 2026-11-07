import pytest

from spotmp3.youtube import track_from_video
from spotmp3.youtube_links import YouTubeLinkError, canonical_url, is_youtube_link, parse_youtube_link, split_video_title

VIDEO_ID = "yybnK-DhphM"


@pytest.mark.parametrize("link", [
    "https://youtu.be/yybnK-DhphM?si=BXBowfUZfLXziybM",
    "https://www.youtube.com/watch?v=yybnK-DhphM",
    "https://youtube.com/watch?v=yybnK-DhphM&list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI&index=3",
    "https://m.youtube.com/watch?feature=share&v=yybnK-DhphM",
    "https://music.youtube.com/watch?v=yybnK-DhphM&si=abc",
    "https://www.youtube.com/shorts/yybnK-DhphM?feature=share",
    "https://www.youtube.com/live/yybnK-DhphM",
    "http://youtu.be/yybnK-DhphM",
    "  https://youtu.be/yybnK-DhphM  ",
])
def test_both_single_video_link_styles_give_the_same_video(link):
    assert is_youtube_link(link)
    assert parse_youtube_link(link) == ("video", VIDEO_ID)


@pytest.mark.parametrize("link", [
    "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
    "https://music.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI&si=x",
])
def test_playlist_links(link):
    assert parse_youtube_link(link) == ("playlist", "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI")


@pytest.mark.parametrize("link", [
    "https://youtu.be/",
    "https://youtu.be/short",
    "https://www.youtube.com/watch?v=bad",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/playlist?list=",
    "ftp://youtu.be/yybnK-DhphM",
])
def test_bad_youtube_links_are_refused(link):
    with pytest.raises(YouTubeLinkError):
        parse_youtube_link(link)


def test_spotify_links_are_not_youtube():
    assert not is_youtube_link("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")
    assert not is_youtube_link("spotify:track:4cOdK2wGLETKBW3PvgPWqT")
    assert not is_youtube_link("https://notyoutube.com/watch?v=yybnK-DhphM")


def test_canonical_urls():
    assert canonical_url("video", VIDEO_ID) == "https://www.youtube.com/watch?v=yybnK-DhphM"
    assert canonical_url("playlist", "PL123") == "https://www.youtube.com/playlist?list=PL123"


def test_video_titles_split_into_artist_and_song():
    assert split_video_title("Daft Punk - Get Lucky (Official Audio)", "Daft Punk") == ("Daft Punk", "Get Lucky")
    assert split_video_title("Some vlog about London", "Tomiwa TP") == ("Tomiwa TP", "Some vlog about London")
    assert split_video_title("Song Name", "Band - Topic") == ("Band", "Song Name")


def test_track_from_video_prefers_music_metadata():
    info = {"id": VIDEO_ID, "title": "whatever", "duration": 200, "track": "Real Title", "artist": "Real Artist", "album": "Real Album"}
    track = track_from_video(info)
    assert (track.title, track.artists, track.album, track.duration_ms, track.youtube_id) == ("Real Title", ("Real Artist",), "Real Album", 200000, VIDEO_ID)
    assert track.cover_url == f"https://i.ytimg.com/vi/{VIDEO_ID}/hqdefault.jpg"


def test_unavailable_videos_are_skipped():
    assert track_from_video({"id": VIDEO_ID, "title": "[Private video]", "duration": None}) is None
    assert track_from_video({"id": VIDEO_ID, "title": "[Deleted video]", "duration": 10}) is None
    assert track_from_video({"id": "bad", "title": "x", "duration": 10}) is None
