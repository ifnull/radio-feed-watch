from radio_feed_watch.extract.phonetic import decode_phonetics


def test_decode_user_example():
    raw = (
        "Two last names. First is Sam, Ocean, Lincoln, Ida, Sam. "
        "Second last name, Charles, Adam, Robert, boy, Adam, John, Adam, Lincoln. "
        "First name of Jose. Middle name, Luis. Date of birth, 07/27/2001."
    )
    result = decode_phonetics(raw)
    assert result.changed
    assert "SOLIS" in result.text
    assert "CARBAJAL" in result.text
    assert "Jose" in result.text
    assert "07/27/2001" in result.text


def test_min_run_avoids_single_name():
    # lone "Sam" / "Lincoln" should not decode
    result = decode_phonetics("Unit Sam on Lincoln Avenue")
    assert not result.changed


def test_nato_mix():
    result = decode_phonetics("Plate is Alpha Bravo Charlie 123")
    assert "ABC" in result.text
