"""What PyPI shows and accepts, checked from the sources."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
PROJECT = PYPROJECT["project"]


def test_readme_links_work_on_pypi():
    # PyPI renders the README without the repository, so relative links break.
    links = re.findall(r"\]\(([^)]+)\)", (ROOT / "README.md").read_text())

    assert links
    assert [link for link in links if not link.startswith(("https://", "#"))] == []


def test_project_has_pypi_metadata():
    assert PROJECT["authors"]
    assert PROJECT["keywords"]
    assert "Environment :: Console" in PROJECT["classifiers"]


def test_python_classifiers_match_the_checked_versions():
    checked = PYPROJECT["tool"]["ghostcrt"]["checks"]["python"]
    listed = [
        c.removeprefix("Programming Language :: Python :: ")
        for c in PROJECT["classifiers"]
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    ]

    assert listed == checked


def test_license_is_an_spdx_expression_without_license_classifiers():
    # PEP 639: a License-Expression must not be combined with License :: classifiers.
    assert PROJECT["license"] == "GPL-3.0-only"
    assert not [c for c in PROJECT["classifiers"] if c.startswith("License ::")]


def test_local_workspaces_stay_out_of_the_sdist():
    excluded = PYPROJECT["tool"]["hatch"]["build"]["exclude"]

    assert "/.ayder" in excluded
    assert "/.superpowers" in excluded
