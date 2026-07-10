"""Detect and annotate APCO/police ten-codes and common radio phrases.

STT often writes codes as words ("ten four") rather than digits ("10-4").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Spoken number words used in ten-codes (and a few ordinals STT invents)
_NUM_WORDS: dict[str, str] = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "for": "4",  # STT often hears "for" instead of "four"
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "niner": "9",
}

# Compound spoken suffixes: "ten twenty" → 10-20, "ten ninety seven" → 10-97
_COMPOUND_NUMS: dict[str, str] = {
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
}

_DIGIT_WORD = (
    r"zero|oh|o|one|two|three|four|for|five|six|seven|eight|nine|niner"
)
_COMPOUND_WORD = (
    r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
)

# Common APCO / LE ten-codes (meaning is advisory — agencies vary)
TEN_CODES: dict[str, str] = {
    "10-1": "unable to copy / poor reception",
    "10-2": "signal good",
    "10-3": "stop transmitting",
    "10-4": "acknowledgment / OK",
    "10-5": "relay",
    "10-6": "busy",
    "10-7": "out of service",
    "10-8": "in service",
    "10-9": "repeat",
    "10-10": "fight in progress / negative",
    "10-13": "weather / road conditions",
    "10-15": "prisoner in custody",
    "10-17": "en route",
    "10-19": "return to station",
    "10-20": "location",
    "10-21": "call by phone",
    "10-22": "disregard",
    "10-23": "arrived at scene",
    "10-27": "driver license info",
    "10-28": "vehicle registration",
    "10-29": "check for wanted",
    "10-32": "person with gun",
    "10-33": "emergency",
    "10-50": "vehicle accident",
    "10-51": "wrecker needed",
    "10-52": "ambulance needed",
    "10-55": "intoxicated driver",
    "10-56": "intoxicated pedestrian",
    "10-76": "en route",
    "10-77": "ETA",
    "10-80": "chase in progress",
    "10-96": "mental subject",
    "10-97": "arrived / on scene",
    "10-98": "finished last assignment",
    "10-99": "wanted / stolen",
}

# Plain radio phrases (not ten-codes).
# Keys are match text; values are (display, meaning).
RADIO_PHRASES: dict[str, tuple[str, str]] = {
    "standby": ("standby", "stand by / wait"),
    "stand by": ("standby", "stand by / wait"),
    "standing by": ("standing by", "standing by"),
    "copy that": ("copy that", "acknowledged"),
    "copy": ("copy", "acknowledged"),
    "roger that": ("roger", "message received"),
    "roger": ("roger", "message received"),
    "wilco": ("wilco", "will comply"),
    "affirmative": ("affirmative", "yes"),
    "negative": ("negative", "no"),
    "go ahead": ("go ahead", "ready to receive"),
    "say again": ("say again", "repeat"),
    "how copy": ("how copy", "confirm reception"),
    "loud and clear": ("loud and clear", "reception good"),
    "be advised": ("be advised", "be advised"),
    "en route": ("en route", "en route"),
    "enroute": ("en route", "en route"),
    "on scene": ("on scene", "on scene"),
    "onscene": ("on scene", "on scene"),
    "code 3": ("code 3", "emergency response (lights/sirens)"),
    "code three": ("code 3", "emergency response (lights/sirens)"),
    "code 4": ("code 4", "no further assistance needed"),
    "code four": ("code 4", "no further assistance needed"),
    "code 2": ("code 2", "urgent, no lights/sirens"),
    "code two": ("code 2", "urgent, no lights/sirens"),
    "code 1": ("code 1", "routine response"),
    "code one": ("code 1", "routine response"),
}

# Digits form: 10-4, 10 4, 10.4, ten-4 mixed
_DIGIT_TEN_RE = re.compile(
    r"\b(?P<code>10)[\s\-./]*(?P<num>\d{1,2})\b",
    re.IGNORECASE,
)

# Spoken compounds first: "ten twenty", "ten ninety-seven", "ten fifty"
_SPOKEN_COMPOUND_RE = re.compile(
    rf"\bten[\s\-./]*(?P<a>{_COMPOUND_WORD})"
    rf"(?:[\s\-./]*(?P<b>{_DIGIT_WORD}))?\b",
    re.IGNORECASE,
)

# Spoken digit-by-digit: "ten four", "ten-four", "ten for", "ten nine seven"
_SPOKEN_TEN_RE = re.compile(
    rf"\bten[\s\-./]*(?P<a>{_DIGIT_WORD})"
    rf"(?:[\s\-./]*(?P<b>{_DIGIT_WORD}))?\b",
    re.IGNORECASE,
)

# Multi-word phrases first (longest match wins via sorted keys)
_PHRASE_PATTERNS: list[tuple[re.Pattern[str], str, str]] = []
for _phrase, (_display, _meaning) in sorted(RADIO_PHRASES.items(), key=lambda kv: -len(kv[0])):
    _PHRASE_PATTERNS.append(
        (
            re.compile(rf"\b{re.escape(_phrase)}\b", re.IGNORECASE),
            _display,
            _meaning,
        )
    )


@dataclass
class RadioCodeHit:
    start: int
    end: int
    raw: str
    normalized: str
    meaning: str | None


@dataclass
class RadioCodeResult:
    text: str
    original: str
    hits: list[RadioCodeHit]

    @property
    def changed(self) -> bool:
        return bool(self.hits)


def _spoken_to_code(a: str, b: str | None) -> str:
    digits = _NUM_WORDS[a.lower()]
    if b:
        digits += _NUM_WORDS[b.lower()]
    return f"10-{digits}"


def _compound_to_code(a: str, b: str | None) -> str:
    base = int(_COMPOUND_NUMS[a.lower()])
    if b:
        base += int(_NUM_WORDS[b.lower()])
    return f"10-{base}"


def _annotate(normalized: str, meaning: str | None) -> str:
    if meaning:
        return f"{normalized} ({meaning})"
    return normalized


def find_radio_codes(text: str) -> list[RadioCodeHit]:
    """Find ten-codes and common radio phrases; non-overlapping, left-to-right."""
    if not text:
        return []

    candidates: list[RadioCodeHit] = []

    for match in _DIGIT_TEN_RE.finditer(text):
        code = f"10-{int(match.group('num'))}"
        candidates.append(
            RadioCodeHit(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                normalized=code,
                meaning=TEN_CODES.get(code),
            )
        )

    for match in _SPOKEN_COMPOUND_RE.finditer(text):
        code = _compound_to_code(match.group("a"), match.group("b"))
        candidates.append(
            RadioCodeHit(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                normalized=code,
                meaning=TEN_CODES.get(code),
            )
        )

    for match in _SPOKEN_TEN_RE.finditer(text):
        code = _spoken_to_code(match.group("a"), match.group("b"))
        candidates.append(
            RadioCodeHit(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                normalized=code,
                meaning=TEN_CODES.get(code),
            )
        )

    for pattern, display, meaning in _PHRASE_PATTERNS:
        for match in pattern.finditer(text):
            candidates.append(
                RadioCodeHit(
                    start=match.start(),
                    end=match.end(),
                    raw=match.group(0),
                    normalized=display,
                    meaning=meaning,
                )
            )

    # Resolve overlaps: prefer longer spans, then earlier start
    candidates.sort(key=lambda h: (-(h.end - h.start), h.start))
    chosen: list[RadioCodeHit] = []
    occupied: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        return any(not (b <= s or a >= e) for s, e in occupied)

    for hit in candidates:
        if overlaps(hit.start, hit.end):
            continue
        # Skip bare "clear"/"over"/"out" only when already covered — already handled by overlap
        occupied.append((hit.start, hit.end))
        chosen.append(hit)

    chosen.sort(key=lambda h: h.start)
    return chosen


def decode_radio_codes(text: str, annotate: bool = True) -> RadioCodeResult:
    """
    Annotate ten-codes and radio phrases in place.

    Example:
      "Ten four standby" -> "10-4 (acknowledgment / OK) standby (stand by / wait)"
    """
    if not text:
        return RadioCodeResult(text=text, original=text, hits=[])

    hits = find_radio_codes(text)
    if not hits:
        return RadioCodeResult(text=text, original=text, hits=[])

    if not annotate:
        return RadioCodeResult(text=text, original=text, hits=hits)

    out: list[str] = []
    cursor = 0
    for hit in hits:
        out.append(text[cursor : hit.start])
        out.append(_annotate(hit.normalized, hit.meaning))
        cursor = hit.end
    out.append(text[cursor:])
    decoded = re.sub(r"\s{2,}", " ", "".join(out)).strip()
    return RadioCodeResult(text=decoded, original=text, hits=hits)
