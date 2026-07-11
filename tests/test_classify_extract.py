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


def test_extract_highway_sh_spaced():
    from radio_feed_watch.extract.address import normalize_road_designations

    # TxDOT compact codes + letter-spaced STT
    assert "State Highway 71" in normalize_road_designations("S H 71")
    assert "State Highway 71" in normalize_road_designations("SH 71")
    assert "FM 969" in normalize_road_designations("F M 969")
    assert "Interstate 35" in normalize_road_designations("I H 35")
    assert "Interstate 35" in normalize_road_designations("IH-35")
    assert "US Highway 290" in normalize_road_designations("U S 290")
    assert "RM 620" in normalize_road_designations("R M 620")
    assert "Park Road 1" in normalize_road_designations("P R 1")
    assert "Park Road 4" in normalize_road_designations("PR 4")

    addrs = extract_addresses("5326 East, S H 71")
    assert addrs
    assert addrs[0].startswith("5326")
    assert "71" in addrs[0]
    assert "Highway" in addrs[0]

    # Spoken TxDOT long form still extracts
    addrs2 = extract_addresses("900 Farm to Market Road 969")
    assert addrs2 and "FM" in addrs2[0] and "969" in addrs2[0]


def test_extract_highway_fm():
    addrs = extract_addresses("1200 FM 969 for a welfare check")
    assert addrs
    assert "1200" in addrs[0]
    assert "FM" in addrs[0]
    assert "969" in addrs[0]


def test_extract_park_road():
    addrs = extract_addresses("200 PR 1A")
    assert addrs
    assert addrs[0] == "200 PR 1A"


def test_format_preserves_house_and_postal_city():
    from radio_feed_watch.geo.proximity import format_us_address

    display = format_us_address(
        {
            "road": "East State Highway 71",
            "county": "Travis County",
            "state": "Texas",
            "postcode": "78617",
        },
        fallback="5326 E Highway 71",
        default_city="Austin",
        default_state="TX",
        postal_cities={"78617": "Del Valle"},
    )
    assert display == "5326 E Highway 71, Del Valle, TX 78617"
