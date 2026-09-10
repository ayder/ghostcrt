from __future__ import annotations

import tomllib
from pathlib import Path

from ghostcrt.config.paths import ensure_config_dir, settings_path
from ghostcrt.models import AppSettings


def load_settings(path: Path | None = None) -> AppSettings:
    p = path if path is not None else settings_path()
    if not p.is_file():
        return AppSettings()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return AppSettings(
        theme=str(data.get("theme", AppSettings.theme)),
        layout_preset=str(data.get("layout_preset", AppSettings.layout_preset)),
    )


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    p = path if path is not None else settings_path()
    if path is None:
        ensure_config_dir()
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f'theme = "{settings.theme}"\n'
        f'layout_preset = "{settings.layout_preset}"\n'
    )
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(p)
