from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_without_keys_shows_setup_warning(monkeypatch, tmp_path):
    # Run from an empty folder so a local .streamlit/secrets.toml is not picked up.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert "GROQ_API_KEY" in at.warning[0].value


def test_app_with_keys_shows_uploader(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert not at.warning  # keys found -> no setup warning, app waits for an upload
