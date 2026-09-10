from pathlib import Path

from ghostcrt.config.settings import load_settings, save_settings
from ghostcrt.models import AppSettings


def test_load_missing_returns_defaults(tmp_home: Path):
    s = load_settings()
    assert s == AppSettings()


def test_save_and_load_roundtrip(tmp_home: Path):
    save_settings(AppSettings(theme="nord", layout_preset="default"))
    s = load_settings()
    assert s.theme == "nord"
