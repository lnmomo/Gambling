from football_agents.official_data.browser import _restricted_access_error


def test_restricted_access_page_is_reported_with_request_id() -> None:
    error = _restricted_access_error("567\nRestricted Access\nProtected by Tencent Cloud EdgeOne", "abc-123")

    assert error is not None
    assert "HTTP 567" in str(error)
    assert "abc-123" in str(error)


def test_chinese_waf_page_is_detected_from_its_status_code_and_request_id() -> None:
    error = _restricted_access_error("567\n访问已受限", "request-567")

    assert error is not None


def test_non_restricted_page_has_no_restriction_diagnostic() -> None:
    assert _restricted_access_error("Football schedule") is None
