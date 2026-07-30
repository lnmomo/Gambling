import json

import pytest

from football_agents.official_data.authorized_feed import (
    AuthorizedOfficialFeedClient,
    _matches_from_payload,
)


def test_authorized_feed_accepts_canonical_matches_envelope() -> None:
    rows = _matches_from_payload({"data": {"matches": [{"source_match_id": "1"}]}})

    assert rows == [{"source_match_id": "1"}]


def test_authorized_feed_rejects_unknown_response_shape() -> None:
    with pytest.raises(RuntimeError, match="must return"):
        _matches_from_payload({"events": []})


def test_authorized_feed_uses_bearer_token_without_exposing_it(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"matches": [{"source_match_id": "1"}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("football_agents.official_data.authorized_feed.urlopen", fake_urlopen)

    payload = AuthorizedOfficialFeedClient(
        "https://licensed.example.test/v1/matches", "secret-token", timeout_seconds=12
    ).fetch()

    assert payload["matches"] == [{"source_match_id": "1"}]
    assert captured["timeout"] == 12
    assert dict((key.lower(), value) for key, value in captured["headers"].items())["authorization"] == "Bearer secret-token"
    assert "secret-token" not in payload["html"]
