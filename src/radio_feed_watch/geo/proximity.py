"""Geocoding + waypoint proximity.

Street-only radio addresses are qualified with the locale city/state/county —
dispatch almost never says them on air.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from geopy.distance import geodesic
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from radio_feed_watch.config import GeocodeLocaleConfig, LocaleConfig, WaypointConfig
from radio_feed_watch.extract.address import highway_query_variants

logger = logging.getLogger(__name__)

_US_STATE_ABBR = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}


@dataclass
class GeocodeResult:
    address: str
    lat: float
    lon: float
    confidence: float
    raw_display: str | None = None
    query: str | None = None


def _state_abbr(state: str | None) -> str | None:
    if not state:
        return None
    s = state.strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return _US_STATE_ABBR.get(s.lower(), s)


def format_us_address(
    details: dict | None,
    *,
    fallback: str,
    default_city: str | None = None,
    default_state: str | None = None,
    postal_cities: dict[str, str] | None = None,
) -> str:
    """Build a compact US display address from Nominatim addressdetails."""
    if not details:
        return fallback

    house = details.get("house_number")
    if not house:
        m = re.match(r"^(\d+)", fallback.strip())
        if m:
            house = m.group(1)

    road = details.get("road") or details.get("pedestrian") or details.get("path")
    # Prefer the extracted street line when OSM only has a road centroid
    fallback_street = re.sub(r",\s*.*$", "", fallback).strip()
    if fallback_street and (
        not road
        or (house and not details.get("house_number"))
        or re.search(r"\b(Highway|FM|RM|Interstate)\b", fallback_street, re.I)
    ):
        street = fallback_street
    else:
        street = " ".join(p for p in (house, road) if p)

    if not street:
        return fallback

    postcode = details.get("postcode")
    city = (
        details.get("city")
        or details.get("town")
        or details.get("village")
        or details.get("hamlet")
        or ((postal_cities or {}).get(postcode) if postcode else None)
        or default_city
    )
    state = _state_abbr(details.get("state") or default_state)

    parts = [street]
    locality = ", ".join(p for p in (city, state) if p)
    if locality and postcode:
        parts.append(f"{locality} {postcode}")
    elif locality:
        parts.append(locality)
    elif postcode:
        parts.append(postcode)
    return ", ".join(parts)


class Geocoder:
    def __init__(self, locale: LocaleConfig):
        self.locale = locale
        self._geolocator = Nominatim(user_agent="radio-feed-watch/0.1")
        self._geocode = RateLimiter(self._geolocator.geocode, min_delay_seconds=1.1)

    def _query_variants(self, address: str, geo: GeocodeLocaleConfig) -> list[str]:
        """Locale-qualified queries — ZIP/city often beat bare county for highways."""
        variants: list[str] = []
        city = geo.default_city
        state = geo.default_state
        county = geo.default_county
        street_forms = highway_query_variants(address)
        is_highway = bool(
            re.search(r"\b(Highway|FM|RM|Interstate|US Highway|Loop|Spur)\b", address, re.I)
        )

        def add_locale(street: str) -> None:
            # For highways, try ZIP / ZIP-city before county (east vs west SH confusion)
            zip_first = is_highway and bool(geo.postal_codes)
            blocks: list[list[str]] = []
            zip_block: list[str] = []
            for zip_code in geo.postal_codes:
                zip_block.append(f"{street}, {zip_code}")
                if state:
                    zip_block.append(f"{street}, {state} {zip_code}")
                zip_city = geo.postal_cities.get(zip_code)
                if zip_city and state:
                    zip_block.append(f"{street}, {zip_city}, {state}")
                    zip_block.append(f"{street}, {zip_city}, {state} {zip_code}")
            county_block: list[str] = []
            if county and state:
                county_block.append(f"{street}, {county}, {state}")
            if county:
                county_block.append(f"{street}, {county}")
            city_block: list[str] = []
            if city and state:
                city_block.append(f"{street}, {city}, {state}")
            elif city:
                city_block.append(f"{street}, {city}")
            if city and county and state:
                city_block.append(f"{street}, {city}, {county}, {state}")

            if zip_first:
                blocks = [zip_block, county_block, city_block, [street]]
            else:
                blocks = [county_block, zip_block, city_block, [street]]
            for block in blocks:
                variants.extend(block)

        for street in street_forms:
            add_locale(street)

        return list(dict.fromkeys(variants))

    @staticmethod
    def _direction_ok(query: str, road: str | None) -> bool:
        """Reject West SH when the transcript said East (and vice versa)."""
        if not road:
            return True
        q = query.lower()
        r = road.lower()
        pairs = (("east", "west"), ("west", "east"), ("north", "south"), ("south", "north"))
        for want, bad in pairs:
            if re.search(rf"\b{want}\b", q) and re.search(rf"\b{bad}\b", r):
                if not re.search(rf"\b{want}\b", r):
                    return False
        return True

    @staticmethod
    def _postal_ok(query: str, details: dict) -> bool:
        """If the query pinned a ZIP, require Nominatim to return that ZIP."""
        m = re.search(r"\b(\d{5})\b", query)
        if not m:
            return True
        want = m.group(1)
        got = details.get("postcode")
        return not got or got == want

    def geocode(self, address: str) -> GeocodeResult | None:
        geo = self.locale.geocode
        kwargs: dict = {"exactly_one": True, "addressdetails": True}
        if geo.country_codes:
            kwargs["country_codes"] = geo.country_codes
        if geo.viewbox:
            # Locale packs store "west,north,east,south".
            # geopy Point is (lat, lon), so corners are (north, west) and (south, east).
            try:
                w, n, e, s = [float(x) for x in geo.viewbox.split(",")]
                kwargs["viewbox"] = ((n, w), (s, e))
                kwargs["bounded"] = True
            except ValueError:
                logger.warning("Invalid viewbox in locale geocode config")

        for variant in self._query_variants(address, geo):
            try:
                loc = self._geocode(variant, **kwargs)
            except Exception:
                logger.exception("Geocode failed for %r", variant)
                continue
            if not loc:
                logger.debug("No geocode hit for %r", variant)
                continue
            if self.locale.bbox:
                b = self.locale.bbox
                if not (b.south <= loc.latitude <= b.north and b.west <= loc.longitude <= b.east):
                    logger.debug("Geocode outside locale bbox for %r: %s", variant, loc)
                    continue

            details = (getattr(loc, "raw", None) or {}).get("address") or {}
            road = details.get("road")
            if not self._direction_ok(variant, road) and not self._direction_ok(address, road):
                logger.debug("Geocode direction mismatch for %r → %r", variant, road)
                continue
            if not self._postal_ok(variant, details):
                logger.debug(
                    "Geocode ZIP mismatch for %r → %r",
                    variant,
                    details.get("postcode"),
                )
                continue

            display = format_us_address(
                details,
                fallback=address,
                default_city=geo.default_city,
                default_state=geo.default_state,
                postal_cities=geo.postal_cities,
            )
            confidence = 0.85 if (
                (geo.default_city and geo.default_city.lower() in variant.lower())
                or (geo.default_county and geo.default_county.lower() in variant.lower())
                or any(z in variant for z in geo.postal_codes)
            ) else 0.6
            return GeocodeResult(
                address=display,
                lat=float(loc.latitude),
                lon=float(loc.longitude),
                confidence=confidence,
                raw_display=getattr(loc, "address", None),
                query=variant,
            )
        return None


def nearest_waypoint(
    lat: float, lon: float, waypoints: list[WaypointConfig], incident_type: str | None = None
) -> tuple[WaypointConfig, float] | None:
    best: tuple[WaypointConfig, float] | None = None
    for wp in waypoints:
        if wp.incident_types and incident_type and incident_type not in wp.incident_types:
            continue
        dist = geodesic((lat, lon), (wp.lat, wp.lon)).meters
        if dist <= wp.radius_m and (best is None or dist < best[1]):
            best = (wp, dist)
    return best
