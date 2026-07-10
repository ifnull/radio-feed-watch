"""Geocoding + waypoint proximity.

Street-only radio addresses are qualified with the locale city/state/county —
dispatch almost never says them on air.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from geopy.distance import geodesic
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from radio_feed_watch.config import GeocodeLocaleConfig, LocaleConfig, WaypointConfig

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
) -> str:
    """Build a compact US display address from Nominatim addressdetails."""
    if not details:
        return fallback

    house = details.get("house_number")
    road = details.get("road") or details.get("pedestrian") or details.get("path")
    city = (
        details.get("city")
        or details.get("town")
        or details.get("village")
        or details.get("hamlet")
        or default_city
    )
    state = _state_abbr(details.get("state") or default_state)
    postcode = details.get("postcode")

    street = " ".join(p for p in (house, road) if p)
    if not street:
        return fallback

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
        """Locale-qualified queries — county/postal often beat city for OSM."""
        variants: list[str] = []
        city = geo.default_city
        state = geo.default_state
        county = geo.default_county

        # County first: many Travis addresses are unincorporated / wrong city in OSM
        if county and state:
            variants.append(f"{address}, {county}, {state}")
        if county:
            variants.append(f"{address}, {county}")

        for zip_code in geo.postal_codes:
            variants.append(f"{address}, {zip_code}")
            if state:
                variants.append(f"{address}, {state} {zip_code}")

        if city and state:
            variants.append(f"{address}, {city}, {state}")
        elif city:
            variants.append(f"{address}, {city}")

        if city and county and state:
            variants.append(f"{address}, {city}, {county}, {state}")

        if address not in variants:
            variants.append(address)

        return list(dict.fromkeys(variants))

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

            details = (getattr(loc, "raw", None) or {}).get("address")
            display = format_us_address(
                details,
                fallback=address,
                default_city=geo.default_city,
                default_state=geo.default_state,
            )
            confidence = 0.85 if (
                (geo.default_city and geo.default_city.lower() in variant.lower())
                or (geo.default_county and geo.default_county.lower() in variant.lower())
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
