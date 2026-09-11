"""ghostcrt package.

``pyproject.toml`` is the single source of truth for the version. An installed
package reads it back from its own metadata; a bare source tree reads the file.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path


def _version_from_pyproject() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def _resolve_version() -> str:
    try:
        return _installed_version("ghostcrt")
    except PackageNotFoundError:
        return _version_from_pyproject()


__version__ = _resolve_version()
