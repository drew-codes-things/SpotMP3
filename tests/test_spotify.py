import pytest

from conftest import embed_page
from spotmp3.spotify import SpotifyLinkError, parse_embed, parse_spotify_link, resolve_link

TRACK_ID = "4cOdK2wGLETKBW3PvgPWqT"
COVER = "https://image-cdn-fa.spotifycdn.com/image/abc"


@pytest.mark.parametrize("link, expected", [
    (f"https://open.spotify.com/track/{TRACK_ID}", ("track", TRACK_ID)),
    (f"https://open.spotify.com/track/{TRACK_ID}?si=0123abcd", ("track", TRACK_ID)),
    (f"https://open.spotify.com/intl-de/track/{TRACK_ID}", ("track", TRACK_ID)),
    (f"https://open.spotify.com/embed/album/{TRACK_ID}", ("album", TRACK_ID)),
    (f"https://open.spotify.com/playlist/{TRACK_ID}?si=x&pi=y", ("playlist", TRACK_ID)),
    (f"spotify:playlist:{TRACK_ID}", ("playlist", TRACK_ID)),
])
def test_spotify_links(link, expected):
    assert parse_spotify_link(link) == expected


@pytest.mark.parametrize("link", [
    "https://open.spotify.com/artist/4cOdK2wGLETKBW3PvgPWqT",
    "https://open.spotify.com/track/short",
    "https://evil.example/track/4cOdK2wGLETKBW3PvgPWqT",
    "not a link",
])
def test_bad_spotify_links(link):
    with pytest.raises(SpotifyLinkError):
        parse_spotify_link(link)


def test_track_embed():
    page = embed_page({"title": "Never Gonna Give You Up", "uri": f"spotify:track:{TRACK_ID}", "duration": 213573,
                       "artists": [{"name": "Rick Astley"}], "visualIdentity": {"image": [{"url": COVER, "maxWidth": 640}]}})
    collection = parse_embed(page, "track")
    track = collection.tracks[0]
    assert (track.title, track.artists, track.duration_ms, track.spotify_id, track.cover_url) == (
        "Never Gonna Give You Up", ("Rick Astley",), 213573, TRACK_ID, COVER)


def test_album_embed_numbers_tracks_and_splits_artists():
    page = embed_page({"name": "An Album", "visualIdentity": {"image": [{"url": COVER, "maxWidth": 300}]}, "trackList": [
        {"title": "One", "subtitle": "A, B", "duration": 1000, "uri": f"spotify:track:{TRACK_ID}"},
        {"title": "Broken", "subtitle": "A"},
        {"title": "Two", "subtitle": "A", "duration": 2000, "uri": "spotify:track:nope"},
    ]})
    collection = parse_embed(page, "album")
    assert [(track.title, track.artists, track.track_number, track.album) for track in collection.tracks] == [
        ("One", ("A", "B"), 1, "An Album"), ("Two", ("A",), 3, "An Album")]
    assert collection.tracks[1].spotify_id is None


def test_playlist_embed_is_marked_cut_short_at_100():
    rows = [{"title": f"T{number}", "subtitle": "A", "duration": 1000} for number in range(100)]
    collection = parse_embed(embed_page({"name": "Big", "trackList": rows}), "playlist")
    assert collection.truncated and len(collection.tracks) == 100


def test_resolve_link_fetches_the_embed_page():
    asked = []

    def fetch(url):
        asked.append(url)
        return embed_page({"name": "P", "trackList": [{"title": "Only", "subtitle": "A", "duration": 5}]})

    collection = resolve_link(f"https://open.spotify.com/playlist/{TRACK_ID}?si=x", fetch)
    assert asked == [f"https://open.spotify.com/embed/playlist/{TRACK_ID}"]
    assert collection.name == "P"


def test_missing_data_is_reported():
    with pytest.raises(SpotifyLinkError):
        parse_embed("<html></html>", "track")
