from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from football_agents.official_data.browser import (
    BROWSER_CANDIDATES,
    SportteryBrowserClient,
    _resolve_browser_path,
)


def test_explicit_path_returned_when_exists(tmp_path: Path) -> None:
    fake = tmp_path / "edge.exe"
    fake.write_text("x")
    assert _resolve_browser_path(str(fake)) == fake


def test_empty_falls_back_to_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the first candidate to "exist" by pointing BROWSER_CANDIDATES at a real temp file.
    fake = Path(__file__).resolve().parent / "fake_browser_marker"
    fake.write_text("x")
    monkeypatch.setattr(
        "football_agents.official_data.browser.BROWSER_CANDIDATES", (str(fake),)
    )
    try:
        resolved = _resolve_browser_path("")
        assert resolved == fake
    finally:
        fake.unlink(missing_ok=True)


def test_invalid_explicit_raises_with_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("football_agents.official_data.browser.BROWSER_CANDIDATES", ())
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(RuntimeError) as exc:
        _resolve_browser_path("C:/does/not/exist/edge.exe")
    assert "OFFICIAL_BROWSER_PATH" in str(exc.value)


def test_no_browser_found_lists_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("football_agents.official_data.browser.BROWSER_CANDIDATES", ("C:/no/a.exe", "C:/no/b.exe"))
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(RuntimeError) as exc:
        _resolve_browser_path("")
    assert "C:/no/a.exe" in str(exc.value)
    assert "PATH:msedge" in str(exc.value)


def test_client_uses_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Path(__file__).resolve().parent / "marker2"
    fake.write_text("x")
    monkeypatch.setattr(
        "football_agents.official_data.browser.BROWSER_CANDIDATES", (str(fake),)
    )
    try:
        client = SportteryBrowserClient("", 10)
        assert client.browser_path == fake
    finally:
        fake.unlink(missing_ok=True)
