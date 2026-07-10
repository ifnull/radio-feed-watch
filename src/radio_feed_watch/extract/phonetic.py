"""Detect and decode police/NATO phonetic alphabet runs in transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass

# LAPD / classic APCO (still common in US LE)
LAPD: dict[str, str] = {
    "adam": "A",
    "boy": "B",
    "baker": "B",
    "box": "B",
    "charles": "C",
    "david": "D",
    "edward": "E",
    "frank": "F",
    "george": "G",
    "henry": "H",
    "ida": "I",
    "john": "J",
    "king": "K",
    "lincoln": "L",
    "mary": "M",
    "nora": "N",
    "ocean": "O",
    "paul": "P",
    "queen": "Q",
    "robert": "R",
    "sam": "S",
    "tom": "T",
    "thomas": "T",
    "union": "U",
    "victor": "V",
    "william": "W",
    "xray": "X",
    "x-ray": "X",
    "young": "Y",
    "yellow": "Y",
    "zebra": "Z",
}

# NATO / ICAO (also heard on some channels)
NATO: dict[str, str] = {
    "alpha": "A",
    "alfa": "A",
    "bravo": "B",
    "charlie": "C",
    "delta": "D",
    "echo": "E",
    "foxtrot": "F",
    "golf": "G",
    "hotel": "H",
    "india": "I",
    "juliet": "J",
    "juliett": "J",
    "kilo": "K",
    "lima": "L",
    "mike": "M",
    "november": "N",
    "oscar": "O",
    "papa": "P",
    "quebec": "Q",
    "romeo": "R",
    "sierra": "S",
    "tango": "T",
    "uniform": "U",
    "victor": "V",
    "whiskey": "W",
    "xray": "X",
    "x-ray": "X",
    "yankee": "Y",
    "zulu": "Z",
}

PHONETIC: dict[str, str] = {**NATO, **LAPD}  # LAPD wins on overlaps like victor

# Token: word or separator; keep punctuation attached lightly
_TOKEN_RE = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?|[0-9]+|[^\w\s]+|\s+")


@dataclass
class PhoneticHit:
    start: int
    end: int
    words: list[str]
    letters: str


@dataclass
class PhoneticResult:
    text: str
    original: str
    hits: list[PhoneticHit]

    @property
    def changed(self) -> bool:
        return bool(self.hits)


def _norm_word(token: str) -> str | None:
    w = token.lower().strip(".,;:!?\"'")
    if not w:
        return None
    return w if w in PHONETIC else None


def find_phonetic_runs(text: str, min_run: int = 2) -> list[PhoneticHit]:
    """Find contiguous runs of phonetic code words (commas/spaces allowed between)."""
    tokens = list(_TOKEN_RE.finditer(text))
    hits: list[PhoneticHit] = []

    i = 0
    while i < len(tokens):
        letter = _norm_word(tokens[i].group(0))
        if not letter:
            i += 1
            continue

        words = [tokens[i].group(0)]
        letters = [PHONETIC[letter]]
        start = tokens[i].start()
        end = tokens[i].end()
        j = i + 1

        while j < len(tokens):
            tok = tokens[j].group(0)
            if tok.isspace() or tok in {",", ";", "/", "-"}:
                j += 1
                continue
            nxt = _norm_word(tok)
            if not nxt:
                break
            words.append(tok)
            letters.append(PHONETIC[nxt])
            end = tokens[j].end()
            j += 1

        if len(letters) >= min_run:
            hits.append(
                PhoneticHit(
                    start=start,
                    end=end,
                    words=words,
                    letters="".join(letters),
                )
            )
            i = j
        else:
            i += 1

    return hits


def decode_phonetics(text: str, min_run: int = 2, annotate: bool = True) -> PhoneticResult:
    """
    Replace phonetic runs with spelled letters.

    Example:
      "Sam, Ocean, Lincoln, Ida, Sam" -> "SOLIS (Sam Ocean Lincoln Ida Sam)"
    """
    if not text:
        return PhoneticResult(text=text, original=text, hits=[])

    hits = find_phonetic_runs(text, min_run=min_run)
    if not hits:
        return PhoneticResult(text=text, original=text, hits=[])

    out: list[str] = []
    cursor = 0
    for hit in hits:
        out.append(text[cursor : hit.start])
        if annotate:
            out.append(f"{hit.letters} ({' '.join(hit.words)})")
        else:
            out.append(hit.letters)
        cursor = hit.end
    out.append(text[cursor:])
    # tidy leftover commas around replacements
    decoded = re.sub(r"\s{2,}", " ", "".join(out))
    decoded = re.sub(r"\s+,", ",", decoded)
    decoded = re.sub(r",\s*\)", ")", decoded)
    return PhoneticResult(text=decoded.strip(), original=text, hits=hits)
