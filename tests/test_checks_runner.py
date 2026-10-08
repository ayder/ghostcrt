import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("checks_runner", ROOT / "scripts" / "checks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TABLE = {
    "uv": "0.12.10",
    "os": ["ubuntu-24.04", "macos-14"],
    "python": ["3.12", "3.14"],
    "step": [
        {"name": "sync", "run": "uv sync --locked"},
        {
            "name": "audit",
            "run": "uvx pip-audit --path {purelib}",
            "only": {"os": "ubuntu-24.04", "python": "3.12"},
        },
        {"name": "build", "run": "uv build --out-dir {dist}"},
        {
            "name": "cli",
            "run": "{smoke}/bin/ghostcrt --version",
            "expect": "ghostcrt {version}",
            "cwd": "tmp",
        },
    ],
}


def test_select_honours_only(runner):
    names = lambda os_name, python: [s["name"] for s in runner.select(TABLE, os_name, python)]

    assert names("ubuntu-24.04", "3.12") == ["sync", "audit", "build", "cli"]
    assert names("ubuntu-24.04", "3.14") == ["sync", "build", "cli"]
    assert names("macos-14", "3.12") == ["sync", "build", "cli"]


def test_command_uses_plain_uv_when_it_is_the_pinned_version(runner):
    assert runner.command("uv build --out-dir {dist}", {"dist": "/d"}, "0.12.10", "0.12.10") == [
        "uv",
        "build",
        "--out-dir",
        "/d",
    ]


def test_command_runs_the_pinned_uv_through_uvx_otherwise(runner):
    assert runner.command("uv sync --locked", {}, "0.12.21", "0.12.10") == [
        "uvx",
        "--from",
        "uv==0.12.10",
        "uv",
        "sync",
        "--locked",
    ]
    assert runner.command("uvx twine==7.0.0 check", {}, None, "0.12.10") == [
        "uvx",
        "--from",
        "uv==0.12.10",
        "uvx",
        "twine==7.0.0",
        "check",
    ]


def test_command_expands_placeholders_and_globs(runner, tmp_path):
    (tmp_path / "ghostcrt-1.0-py3-none-any.whl").touch()
    (tmp_path / "ghostcrt-1.0.tar.gz").touch()

    argv = runner.command("uvx twine check {dist}/*", {"dist": str(tmp_path)}, "0.12.10", "0.12.10")

    assert argv[:3] == ["uvx", "twine", "check"]
    assert sorted(Path(p).name for p in argv[3:]) == [
        "ghostcrt-1.0-py3-none-any.whl",
        "ghostcrt-1.0.tar.gz",
    ]


def test_command_leaves_non_uv_programs_alone(runner):
    assert runner.command(
        "{smoke}/bin/ghostcrt --version", {"smoke": "/s"}, "0.12.21", "0.12.10"
    ) == [
        "/s/bin/ghostcrt",
        "--version",
    ]


def test_default_os_follows_the_platform(runner):
    assert runner.default_os(TABLE, "Darwin") == "macos-14"
    assert runner.default_os(TABLE, "Linux") == "ubuntu-24.04"


def test_project_table_is_what_the_runner_reads(runner):
    table = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ghostcrt"]["checks"]

    assert runner.load_checks() == table
