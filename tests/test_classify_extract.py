"""Unit tests for classifiers and address extraction."""

from radio_feed_watch.classify.rules import classify_incident
from radio_feed_watch.extract.address import extract_addresses
from radio_feed_watch.geo.proximity import Geocoder
from radio_feed_watch.config import LocaleConfig, GeocodeLocaleConfig
from radio_feed_watch.models import IncidentType


def test_classify_structure_fire():
    itype, conf = classify_incident("Engine 5 responding structure fire at the warehouse")
    assert itype == IncidentType.STRUCTURE_FIRE
    assert conf > 0.5


def test_classify_mvc():
    itype, conf = classify_incident("MVC with injuries on the freeway")
    assert itype == IncidentType.VEHICLE_ACCIDENT
    assert conf > 0.5


def test_extract_street_address():
    addrs = extract_addresses("Responding to 123 Main Street for a fire alarm")
    assert any("123 Main Street" in a for a in addrs)


def test_extract_long_street_name():
    addrs = extract_addresses("19125 James Carter Junior Street")
    assert addrs
    assert "19125" in addrs[0]
    assert "James Carter" in addrs[0]
    assert "Street" in addrs[0]
    # Junior normalized toward Jr for geocoders
    assert "Jr" in addrs[0] or "Junior" in addrs[0]


def test_extract_block_of():
    addrs = extract_addresses("13900 Block of SME 12")
    assert addrs
    assert addrs[0].startswith("13900")


def test_extract_intersection():
    addrs = extract_addresses("Units at Congress and 6th for an MVC")
    assert addrs
    assert "Congress" in addrs[0]
    assert "6th" in addrs[0]


def test_extract_named_intersection():
    addrs = extract_addresses("coming to a stop, West Olympic Drive and Heather Weld")
    assert addrs
    assert "Olympic" in addrs[0] or "Heather" in addrs[0]


def test_geocode_variants_prefer_county_then_city():
    locale = LocaleConfig(
        id="test",
        label="Test",
        geocode=GeocodeLocaleConfig(
            default_city="Austin",
            default_state="TX",
            default_county="Travis County",
            postal_codes=["78734"],
        ),
    )
    g = Geocoder(locale)
    variants = g._query_variants("19125 James Carter Jr Street", locale.geocode)
    assert variants[0] == "19125 James Carter Jr Street, Travis County, TX"
    assert "19125 James Carter Jr Street, Austin, TX" in variants
    assert "19125 James Carter Jr Street, 78734" in variants
    assert "19125 James Carter Jr Street" in variants


def test_format_us_address_uses_default_city():
    from radio_feed_watch.geo.proximity import format_us_address

    display = format_us_address(
        {
            "house_number": "123",
            "road": "Example Trail",
            "county": "Travis County",
            "state": "Texas",
            "postcode": "78734",
        },
        fallback="123 Example Trail",
        default_city="Austin",
        default_state="TX",
    )
    assert display == "123 Example Trail, Austin, TX 78734"
