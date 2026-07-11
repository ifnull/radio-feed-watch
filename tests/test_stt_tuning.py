from radio_feed_watch.config import DeepgramSttConfig
from radio_feed_watch.stt.deepgram import DeepgramTranscriber, _uses_keyterm


def test_uses_keyterm_for_nova3():
    assert _uses_keyterm("nova-3")
    assert _uses_keyterm("nova-3-general")
    assert not _uses_keyterm("nova-2-phonecall")


def test_deepgram_params_keywords_for_nova2():
    t = DeepgramTranscriber(
        DeepgramSttConfig(model="nova-2-phonecall", keyword_intensifier=2),
        api_key="x",
        locale_vocab=["Lakeway", "ten-four"],
    )
    pairs = t._build_params()
    as_dict = {}
    keywords = []
    for k, v in pairs:
        if k == "keywords":
            keywords.append(v)
        else:
            as_dict[k] = v
    assert as_dict["model"] == "nova-2-phonecall"
    assert as_dict["numerals"] == "true"
    assert any(k.startswith("Lakeway:") for k in keywords)
    assert any("ten-four" in k.lower() for k in keywords)


def test_deepgram_params_keyterm_for_nova3():
    t = DeepgramTranscriber(
        DeepgramSttConfig(model="nova-3", keywords=["standby"]),
        api_key="x",
        locale_vocab=["MoPac"],
    )
    pairs = t._build_params()
    keyterms = [v for k, v in pairs if k == "keyterm"]
    assert "standby" in keyterms
    assert "MoPac" in keyterms
    assert not any(k == "keywords" for k, _ in pairs)
