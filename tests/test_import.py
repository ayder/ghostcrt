import tomllib
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import ghostcrt

PYPROJECT_VERSION = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]


def test_package_imports():
    # pyproject.toml is the single source of truth; 0.2.0 shipped saying 0.1.0.
    assert ghostcrt.__version__ == PYPROJECT_VERSION


def test_version_falls_back_to_pyproject_when_not_installed(monkeypatch):
    def not_installed(_name):
        raise PackageNotFoundError("ghostcrt")

    monkeypatch.setattr(ghostcrt, "_installed_version", not_installed)
    assert ghostcrt._resolve_version() == PYPROJECT_VERSION
