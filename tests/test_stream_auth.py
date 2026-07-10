from radio_feed_watch.sources.broadcastify_stream import basic_auth_header


def test_basic_auth_header():
    # base64("user:pass")
    assert basic_auth_header("user", "pass") == "Basic dXNlcjpwYXNz"
