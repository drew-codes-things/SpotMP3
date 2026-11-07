from spotmp3.matching import Candidate, choose_best, duration_fits, music_result_plausible, score
from spotmp3.tracks import Track

TRACK = Track(title="Get Lucky", artists=("Daft Punk", "Pharrell Williams"), duration_ms=248000)


def candidate(title, seconds, channel="Daft Punk", video_id="aaaaaaaaaaa", verified=False):
    return Candidate(video_id, title, channel, seconds, verified)


def test_official_audio_beats_a_live_version_and_a_wrong_length():
    picks = [
        candidate("Daft Punk - Get Lucky (Live at the Grammys)", 249, video_id="live0000000"),
        candidate("Daft Punk - Get Lucky (Radio Edit)", 190, video_id="radio000000"),
        candidate("Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams", 248, video_id="right000000", verified=True),
    ]
    assert choose_best(TRACK, picks).video_id == "right000000"


def test_variants_are_allowed_when_the_spotify_title_asks_for_them():
    live = Track(title="Get Lucky - Live", artists=("Daft Punk",), duration_ms=300000)
    assert score(live, candidate("Daft Punk - Get Lucky (Live)", 300)) is not None
    assert score(TRACK, candidate("Daft Punk - Get Lucky (Live)", 248)) is None


def test_nothing_close_enough_gives_no_match():
    assert choose_best(TRACK, [candidate("Completely different song", 248)]) is None
    assert choose_best(TRACK, [candidate("Get Lucky", None)]) is None
    assert choose_best(TRACK, []) is None


def test_duration_tolerance():
    assert duration_fits(TRACK, 251)
    assert not duration_fits(TRACK, 260)
    assert not duration_fits(TRACK, None)


def test_music_search_result_check():
    assert music_result_plausible(TRACK, candidate("Get Lucky", None))
    assert not music_result_plausible(TRACK, candidate("Get Lucky (Karaoke Version)", None))
