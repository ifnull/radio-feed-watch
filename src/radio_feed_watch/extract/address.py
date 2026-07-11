"""Street-level address extraction for radio transcripts.

Dispatchers almost never say city/state — the locale pack supplies that for geocoding.

Texas route designations follow TxDOT freeway guide-sign abbreviations:
https://www.txdot.gov/manuals/trf/fsh/freeway_guide_sign_design/guide_sign_elements/abbreviations-i1007748.html

STT often spells them letter-by-letter ("S H 71"); we collapse then expand for geocoders.
"""

from __future__ import annotations

import re

# Includes TxDOT guide-sign street-type abbreviations (Ave, Blvd, Dr, Frwy/Fwy, …)
STREET_SUFFIXES = (
    "street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln|court|ct|"
    "circle|cir|way|parkway|pkwy|place|pl|terrace|ter|trail|trl|tr|highway|hwy|"
    "freeway|fwy|frwy|expressway|expy|expwy|beltway|bltwy|causeway|cswy|"
    "loop|run|path|pike|alley|aly|bridge|crossing|xing|square|sq|commons"
)

# Optional leading direction
_DIR = r"(?:[nsew]|north|south|east|west|northeast|northwest|southeast|southwest)\.?"

# Words that must not be part of a street name (radio filler / grammar).
_STOP = (
    r"a|an|the|and|or|&|at|on|of|for|to|from|with|by|in|near|into|onto|"
    r"unit|units|officer|clear|copy|show|go|coming|stop|traffic|"
    r"responding|respond|enroute|en|route|call|scene|location"
)

_NAME_TOKEN = rf"(?!{_STOP}\b)[A-Za-z0-9][A-Za-z0-9.'\-]*"
_STREET_NAME = rf"(?:{_DIR}\s+)?{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,6}}"
_INTERSECTION_NAME = rf"(?:{_DIR}\s+)?{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,3}}"

# Cardinal direction before a highway (optional comma from STT: "East, S H 71")
_HWY_DIR = r"(?:[nsew]|north|south|east|west)\.?"

# TxDOT route types + common spoken forms.
# SH=State Highway, FM=Farm to Market, RM=Ranch to Market, IH=Interstate,
# PR=Park Road, US=United States, ALT=Alternate.
_HWY_ROUTE = (
    r"(?:state\s+highway|state\s+route|highway|hwy\.?|"
    r"farm(?:\s*[-–]?\s*to\s*[-–]?\s*market)?(?:\s+road)?|farm\s+road|fm|"
    r"ranch(?:\s*[-–]?\s*to\s*[-–]?\s*market)?(?:\s+road)?|ranch\s+road|rm|rr|"
    r"park\s+road|pr|"
    r"interstate|ih|i|"
    r"us\s+highway|u\.?s\.?|us|"
    r"alternate|alt|"
    r"loop|spur|beltway|bltwy|parkway|pkwy|"
    r"sh|sr)"
    r"\s*-?\s*"
    r"(\d{1,4}[A-Za-z]?)"
)

HIGHWAY_ADDRESS_RE = re.compile(
    rf"\b(\d{{1,6}})\s+(?:({_HWY_DIR})\.?,?\s+)?(?:{_HWY_ROUTE})\b",
    re.IGNORECASE,
)

ADDRESS_RE = re.compile(
    rf"\b(\d{{1,6}})\s+({_STREET_NAME})\s+({STREET_SUFFIXES})\b",
    re.IGNORECASE,
)

BLOCK_RE = re.compile(
    rf"\b(\d{{1,6}})\s+(?:hundred\s+)?block(?:\s+of)?\s+({_STREET_NAME})"
    rf"(?:\s+({STREET_SUFFIXES}))?\b",
    re.IGNORECASE,
)

INTERSECTION_RE = re.compile(
    rf"\b({_INTERSECTION_NAME})\s+(?:and|&|@)\s+({_INTERSECTION_NAME})"
    rf"(?:\s+({STREET_SUFFIXES}))?\b",
    re.IGNORECASE,
)

ON_STREET_RE = re.compile(
    rf"\b(?:on|at|near)\s+({_STREET_NAME})\s+({STREET_SUFFIXES})\b",
    re.IGNORECASE,
)

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

# Letter-spaced STT → TxDOT compact designation
_SPACED_DESIGNATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bF\s+M\b", re.I), "FM"),
    (re.compile(r"\bR\s+M\b", re.I), "RM"),
    (re.compile(r"\bR\s+R\b", re.I), "RR"),
    (re.compile(r"\bP\s+R\b", re.I), "PR"),
    (re.compile(r"\bS\s+H\b", re.I), "SH"),
    (re.compile(r"\bS\s+R\b", re.I), "SR"),
    (re.compile(r"\bI\s+H\b", re.I), "IH"),
    (re.compile(r"\bU\s+S\b", re.I), "US"),
    (re.compile(r"\bA\s+L\s+T\b", re.I), "ALT"),
]

# Compact TxDOT codes → geocoder-friendly expansion
_EXPAND_DESIGNATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bSH\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"State Highway \1"),
    (re.compile(r"\bSR\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"State Route \1"),
    (re.compile(r"\bIH\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"Interstate \1"),
    (re.compile(r"\bI\s*-\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"Interstate \1"),
    (re.compile(r"\bI\s+(\d{1,4}[A-Za-z]?)\b", re.I), r"Interstate \1"),
    (re.compile(r"\bUS\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"US Highway \1"),
    (re.compile(r"\bU\.S\.?\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"US Highway \1"),
    (re.compile(r"\bHwy\.?\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"Highway \1"),
    (re.compile(r"\bFM\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"FM \1"),
    (re.compile(r"\bRM\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"RM \1"),
    (re.compile(r"\bRR\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"RM \1"),
    (re.compile(r"\bPR\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"Park Road \1"),
    (re.compile(r"\bALT\s*-?\s*(\d{1,4}[A-Za-z]?)\b", re.I), r"Alternate \1"),
]


def normalize_road_designations(text: str) -> str:
    """Collapse 'S H 71' → 'SH 71' → 'State Highway 71' (TxDOT + STT forms)."""
    if not text:
        return text
    out = text
    for pattern, repl in _SPACED_DESIGNATIONS:
        out = pattern.sub(repl, out)
    for pattern, repl in _EXPAND_DESIGNATIONS:
        out = pattern.sub(repl, out)
    return out


def _dir_abbrev(direction: str | None) -> str:
    if not direction:
        return ""
    d = direction.strip(" .,").lower()
    mapping = {
        "n": "N",
        "north": "N",
        "s": "S",
        "south": "S",
        "e": "E",
        "east": "E",
        "w": "W",
        "west": "W",
    }
    return mapping.get(d, direction.strip(" .,").title())


def _format_highway(num: str, direction: str | None, route_num: str, matched: str) -> str:
    """Canonical display: '5326 E Highway 71' / '1200 FM 969' / '400 PR 1'."""
    low = matched.lower()
    if re.search(r"\bfm\b|farm", low):
        label = "FM"
    elif re.search(r"\bpr\b|park\s+road", low):
        label = "PR"
    elif re.search(r"\brm\b|\brr\b|ranch", low):
        label = "RM"
    elif re.search(r"interstate|\bih\b", low) or re.search(r"\bi\s*-?\s*\d", low):
        label = "Interstate"
    elif re.search(r"us\s+highway|\bus\b|u\.s", low):
        label = "US Highway"
    elif re.search(r"\balt(?:ernate)?\b", low):
        label = "Alternate"
    elif re.search(r"\bloop\b", low):
        label = "Loop"
    elif re.search(r"\bspur\b", low):
        label = "Spur"
    elif re.search(r"beltway|bltwy", low):
        label = "Beltway"
    elif re.search(r"state\s+route|\bsr\b", low):
        label = "State Route"
    else:
        # SH / State Highway / Highway / Hwy (TxDOT: SH)
        label = "Highway"

    d = _dir_abbrev(direction)
    parts = [num]
    if d:
        parts.append(d)
    parts.append(label)
    parts.append(route_num)
    return " ".join(parts)


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,.;:")
    s = re.sub(r"\bJunior\b", "Jr", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSenior\b", "Sr", s, flags=re.IGNORECASE)
    return s


def extract_addresses(text: str) -> list[str]:
    """Return street-level address candidates (no city/state required)."""
    if not text:
        return []

    text = normalize_road_designations(text)
    found: list[str] = []
    highway_houses: set[str] = set()

    # Highways first — otherwise ADDRESS_RE steals "5326 E Highway" and drops "71"
    for match in HIGHWAY_ADDRESS_RE.finditer(text):
        num, direction, route_num = match.group(1), match.group(2), match.group(3)
        found.append(_clean(_format_highway(num, direction, route_num, match.group(0))))
        highway_houses.add(num)

    for match in ADDRESS_RE.finditer(text):
        if match.group(1) in highway_houses:
            continue
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


def highway_query_variants(address: str) -> list[str]:
    """Extra geocode spellings for highway addresses (best Nominatim forms first)."""
    variants: list[str] = []

    def expand_cardinals(s: str) -> str:
        s = re.sub(r"\bE\b", "East", s)
        s = re.sub(r"\bW\b", "West", s)
        s = re.sub(r"\bN\b", "North", s)
        s = re.sub(r"\bS\b(?!\s*tate)", "South", s)
        return s

    long_dir = expand_cardinals(address)
    state_hwy = re.sub(r"\bHighway\b", "State Highway", address, flags=re.I)
    state_hwy_long = re.sub(r"\bHighway\b", "State Highway", long_dir, flags=re.I)

    for v in (
        state_hwy_long,
        state_hwy,
        long_dir,
        address,
        re.sub(r"\bState Highway\b", "Highway", address, flags=re.I),
        re.sub(r"\bFM\b", "Farm to Market Road", address, flags=re.I),
        re.sub(r"\bRM\b", "Ranch Road", address, flags=re.I),
        re.sub(r"\bPR\b", "Park Road", address, flags=re.I),
        re.sub(r"\bPark Road\b", "PR", address, flags=re.I),
        re.sub(r"\bInterstate\b", "IH", address, flags=re.I),
        re.sub(r"\bIH\b", "Interstate", address, flags=re.I),
    ):
        if v and v not in variants:
            variants.append(v)
    return variants
