"""Street-level address extraction for radio transcripts.

Dispatchers almost never say city/state — the locale pack supplies that for geocoding.
"""

from __future__ import annotations

import re

STREET_SUFFIXES = (
    "street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln|court|ct|"
    "circle|cir|way|parkway|pkwy|place|pl|terrace|ter|trail|trl|highway|hwy|"
    "freeway|fwy|expressway|expy|loop|run|path|pike|alley|aly|bridge|crossing|"
    "square|sq|commons"
)

# Optional leading direction
_DIR = r"(?:[nsew]|north|south|east|west|northeast|northwest|southeast|southwest)\.?"

# Words that must not be part of a street name (radio filler / grammar).
# Without this, greedy name patterns swallow "Units at Congress and 6th for …".
_STOP = (
    r"a|an|the|and|or|&|at|on|of|for|to|from|with|by|in|near|into|onto|"
    r"unit|units|officer|clear|copy|show|go|coming|stop|traffic|"
    r"responding|respond|enroute|en|route|call|scene|location"
)

# Street name tokens: words, initials, Jr/Sr/numbered ordinals — not stop words
_NAME_TOKEN = rf"(?!{_STOP}\b)[A-Za-z0-9][A-Za-z0-9.'\-]*"
# Allow longer names: "James Carter Junior", "Martin Luther King Jr"
_STREET_NAME = rf"(?:{_DIR}\s+)?{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,6}}"
# Intersections are usually short: "Congress", "6th", "West Olympic"
_INTERSECTION_NAME = rf"(?:{_DIR}\s+)?{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,3}}"

# 19125 James Carter Junior Street / 123 N Main St
ADDRESS_RE = re.compile(
    rf"\b(\d{{1,6}})\s+({_STREET_NAME})\s+({STREET_SUFFIXES})\b",
    re.IGNORECASE,
)

# 13900 block of Main Street / 1200 hundred block of Congress Ave
BLOCK_RE = re.compile(
    rf"\b(\d{{1,6}})\s+(?:hundred\s+)?block(?:\s+of)?\s+({_STREET_NAME})"
    rf"(?:\s+({STREET_SUFFIXES}))?\b",
    re.IGNORECASE,
)

# Main and Oak / Congress @ 6th  (avoid bare "at" — too many false hits like "units at …")
INTERSECTION_RE = re.compile(
    rf"\b({_INTERSECTION_NAME})\s+(?:and|&|@)\s+({_INTERSECTION_NAME})"
    rf"(?:\s+({STREET_SUFFIXES}))?\b",
    re.IGNORECASE,
)

# "stop at West Olympic Drive" / "on Heather Weld Street"
ON_STREET_RE = re.compile(
    rf"\b(?:on|at|near)\s+({_STREET_NAME})\s+({STREET_SUFFIXES})\b",
    re.IGNORECASE,
)

# Noise tokens that should not start a street name alone in intersections
_BAD_INTERSECTION_LEFT = {
    "unit",
    "units",
    "engine",
    "medic",
    "ladder",
    "officer",
    "clear",
    "copy",
    "show",
    "go",
    "coming",
    "stop",
    "traffic",
}


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,.;:")
    # normalize Jr. variants for geocoders
    s = re.sub(r"\bJunior\b", "Jr", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSenior\b", "Sr", s, flags=re.IGNORECASE)
    return s


def extract_addresses(text: str) -> list[str]:
    """Return street-level address candidates (no city/state required)."""
    if not text:
        return []

    found: list[str] = []

    for match in ADDRESS_RE.finditer(text):
        found.append(_clean(match.group(0)))

    for match in BLOCK_RE.finditer(text):
        num, name, suffix = match.group(1), match.group(2), match.group(3)
        if suffix:
            found.append(_clean(f"{num} {name} {suffix}"))
        else:
            found.append(_clean(f"{num} {name}"))

    for match in INTERSECTION_RE.finditer(text):
        left = match.group(1).strip()
        first = left.split()[0].lower() if left else ""
        if first in _BAD_INTERSECTION_LEFT:
            continue
        found.append(_clean(match.group(0)))

    if not found:
        for match in ON_STREET_RE.finditer(text):
            found.append(_clean(f"{match.group(1)} {match.group(2)}"))

    numbered = [a for a in found if re.match(r"^\d+", a)]
    if numbered:
        return list(dict.fromkeys(numbered))
    return list(dict.fromkeys(found))
