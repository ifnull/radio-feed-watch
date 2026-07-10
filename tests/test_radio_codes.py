from radio_feed_watch.extract.radio_codes import decode_radio_codes, find_radio_codes


def test_ten_four_spoken():
    result = decode_radio_codes("Ten four standby")
    assert "10-4" in result.text
    assert "standby" in result.text.lower()
    assert len(result.hits) >= 2
    norms = {h.normalized for h in result.hits}
    assert "10-4" in norms
    assert "standby" in norms


def test_ten_four_digits():
    result = decode_radio_codes("10-4, we are 10-97")
    norms = [h.normalized for h in result.hits]
    assert "10-4" in norms
    assert "10-97" in norms


def test_ten_twenty_spoken():
    result = decode_radio_codes("what's your ten twenty")
    assert any(h.normalized == "10-20" for h in result.hits)
    assert "location" in result.text


def test_ten_ninety_seven():
    result = decode_radio_codes("we are ten ninety seven")
    assert any(h.normalized == "10-97" for h in result.hits)


def test_ten_for_stt_mishear():
    # STT often writes "for" instead of "four"
    hits = find_radio_codes("ten for, copy")
    assert any(h.normalized == "10-4" for h in hits)


def test_code_three():
    result = decode_radio_codes("responding code three")
    assert any(h.normalized == "code 3" for h in result.hits)


def test_no_false_ten_in_address():
    # "ten" alone in a street name shouldn't invent a ten-code without a number word
    hits = find_radio_codes("on Tenaya Street")
    assert not any(h.normalized.startswith("10-") for h in hits)
