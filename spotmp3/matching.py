import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .tracks import Track

VARIANT_WORDS = (
    "live", "cover", "karaoke", "instrumental", "remix", "sped up", "speed up", "slowed", "nightcore",
    "8d", "reverb", "extended", "acoustic", "piano version", "reaction", "tutorial", "lesson", "mashup", "bass boosted",
)
OFFICIAL_HINTS = ("official audio", "official music video", "official video", "provided to youtube", "audio")
BRACKETED = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
FEATURING = re.compile(r"\b(feat|ft|featuring|with)\b\.?.*$")
NON_WORD = re.compile(r"[^\w\s]")

MAX_DURATION_GAP_SECONDS = 15
DURATION_TOLERANCE_SECONDS = 4
DURATION_TOLERANCE_SHARE = 0.03
MIN_TITLE_SIMILARITY = 0.55
MIN_ACCEPTED_SCORE = 0.55


@dataclass(frozen=True)
class Candidate:
    video_id: str
    title: str
    channel: str
    duration_seconds: float | None
    verified: bool = False
    from_music_search: bool = False


def normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    lowered = ascii_text.lower().replace("&", " and ")
    return " ".join(NON_WORD.sub(" ", lowered).split())


def core_title(title: str) -> str:
    without_brackets = BRACKETED.sub(" ", title or "")
    without_dash_tail = re.split(r"\s[-–]\s(?=.*\b(remaster|version|edit|mix)\b)", without_brackets, flags=re.I)[0]
    return FEATURING.sub("", normalise(without_dash_tail)).strip()


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def contains_phrase(haystack: str, phrase: str) -> bool:
    return re.search(rf"(^|\s){re.escape(phrase)}(\s|$)", haystack) is not None


def unwanted_variants(track: Track, candidate: Candidate) -> list[str]:
    wanted = normalise(track.title)
    offered = normalise(candidate.title)
    return [word for word in VARIANT_WORDS if contains_phrase(offered, word) and not contains_phrase(wanted, word)]


def duration_fits(track: Track, seconds: float | None) -> bool:
    if seconds is None:
        return False
    expected = track.duration_ms / 1000
    allowed = max(DURATION_TOLERANCE_SECONDS, expected * DURATION_TOLERANCE_SHARE)
    return abs(seconds - expected) <= allowed


def title_similarity(track: Track, candidate: Candidate) -> float:
    wanted = core_title(track.title)
    offered = normalise(candidate.title)
    if wanted and contains_phrase(offered, wanted):
        return 1.0
    for artist_name in filter(None, map(normalise, track.artists)):
        offered = offered.replace(artist_name, " ")
    return similarity(wanted, core_title(offered))


def artist_mentioned(track: Track, candidate: Candidate) -> bool:
    place = normalise(f"{candidate.title} {candidate.channel}")
    return any(contains_phrase(place, normalise(artist)) for artist in track.artists if normalise(artist))


def score(track: Track, candidate: Candidate) -> float | None:
    if unwanted_variants(track, candidate):
        return None
    if candidate.duration_seconds is None:
        return None
    gap = abs(candidate.duration_seconds - track.duration_ms / 1000)
    if gap > MAX_DURATION_GAP_SECONDS:
        return None
    title_score = title_similarity(track, candidate)
    if title_score < MIN_TITLE_SIMILARITY:
        return None
    total = 0.45 * title_score + 0.3 * max(0.0, 1 - gap / MAX_DURATION_GAP_SECONDS)
    if artist_mentioned(track, candidate):
        total += 0.15
    channel = normalise(candidate.channel)
    title = normalise(candidate.title)
    if candidate.verified or channel.endswith(" topic"):
        total += 0.05
    if any(contains_phrase(title, hint) for hint in OFFICIAL_HINTS):
        total += 0.05
    return total


def choose_best(track: Track, candidates: list[Candidate]) -> Candidate | None:
    scored = [(score(track, candidate), index, candidate) for index, candidate in enumerate(candidates)]
    accepted = [(value, index, candidate) for value, index, candidate in scored if value is not None and value >= MIN_ACCEPTED_SCORE]
    if not accepted:
        return None
    return max(accepted, key=lambda entry: (entry[0], -entry[1]))[2]


def music_result_plausible(track: Track, candidate: Candidate) -> bool:
    return not unwanted_variants(track, candidate) and title_similarity(track, candidate) >= MIN_TITLE_SIMILARITY
