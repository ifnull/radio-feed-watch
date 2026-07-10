"""JWT helper unit tests (no network)."""

from radio_feed_watch.sources.broadcastify_calls import generate_broadcastify_jwt


def test_jwt_shape():
    token = generate_broadcastify_jwt("kid", "secret", "app", uid="1", user_token="utk")
    parts = token.split(".")
    assert len(parts) == 3
    assert all(parts)