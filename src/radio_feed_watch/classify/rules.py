"""Keyword incident-type classifier."""

from __future__ import annotations

import re

from radio_feed_watch.models import IncidentType

DEFAULT_PHRASES: dict[str, list[str]] = {
    IncidentType.STRUCTURE_FIRE.value: ["structure fire", "working fire", "box alarm"],
    IncidentType.FIRE.value: ["fire", "smoke", "alarm"],
    IncidentType.VEHICLE_ACCIDENT.value: [
        "mvc",
        "motor vehicle",
        "vehicle accident",
        "traffic accident",
        "collision",
    ],
    IncidentType.DUI.value: ["dui", "dwi", "intoxicated"],
    IncidentType.MEDICAL.value: [
        "chest pain",
        "cardiac",
        "stroke",
        "unresponsive",
        "medical",
        "ems",
    ],
    IncidentType.SHOOTING.value: ["shooting", "shots fired", "gunshot"],
    IncidentType.ROBBERY.value: ["robbery", "armed robbery"],
    IncidentType.TRAFFIC_STOP.value: ["traffic stop", "vehicle stop"],
    IncidentType.HAZMAT.value: ["hazmat", "gas leak", "chemical"],
    IncidentType.RESCUE.value: ["rescue", "water rescue", "trapped"],
}


def classify_incident(text: str, locale_phrases: dict[str, list[str]] | None = None) -> tuple[IncidentType, float]:
    """Return (incident_type, confidence) from keyword rules."""
    hay = text.lower()
    phrases = {**DEFAULT_PHRASES}
    if locale_phrases:
        for key, vals in locale_phrases.items():
            phrases.setdefault(key, [])
            phrases[key] = list(dict.fromkeys([*phrases[key], *vals]))

    best_type = IncidentType.UNKNOWN
    best_score = 0.0
    for type_key, words in phrases.items():
        try:
            itype = IncidentType(type_key)
        except ValueError:
            continue
        for phrase in words:
            if not phrase:
                continue
            if re.search(rf"\b{re.escape(phrase.lower())}\b", hay):
                # longer phrases win slightly
                score = 0.55 + min(len(phrase), 40) / 100.0
                if score > best_score:
                    best_score = score
                    best_type = itype
    if best_type == IncidentType.UNKNOWN:
        return IncidentType.UNKNOWN, 0.0
    return best_type, min(best_score, 0.95)
