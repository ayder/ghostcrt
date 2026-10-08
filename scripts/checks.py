#!/usr/bin/env python3
"""Run the checks listed in pyproject.toml under [tool.ghostcrt.checks].

CI runs this once per os/python pair. Locally:

    uv run --no-project python scripts/checks.py          # this OS, every python
    uv run --no-project python scripts/checks.py --all    # plus the ubuntu jobs in Docker

Both run the same table, so a green local run is the CI result. Steps use the
table's uv version even when the installed uv differs, and each pair gets its
own project environment, so a run never replaces the developer's .venv.
tests/test_ci_drift.py keeps .github/workflows in step with the table.
"""

from __future__ import annotations

import argparse
import glob
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURELIB = "uv run --no-sync python -c \"import sysconfig; print(sysconfig.get_path('purelib'))\""


def load_project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def load_checks() -> dict:
    return load_project()["tool"]["ghostcrt"]["checks"]


def default_os(table: dict, system: str | None = None) -> str:
    family = {"Darwin": "macos", "Linux": "ubuntu"}[system or platform.system()]
    return next(name for name in table["os"] if name.startswith(family))


def select(table: dict, os_name: str, python: str) -> list[dict]:
    """The steps that run for one os/python pair."""
    pair = {"os": os_name, "python": python}
    return [
        step
        for step in table["step"]
        if all(pair[key] == value for key, value in step.get("only", {}).items())
    ]


def installed_uv() -> str | None:
    try:
        out = subprocess.run(["uv", "--version"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    words = out.split()
    return words[1] if len(words) > 1 else None


def fill(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def command(run: str, values: dict[str, str], local_uv: str | None, pinned_uv: str) -> list[str]:
    """One step's argv: placeholders and globs expanded, uv pinned to the table's version."""
    argv: list[str] = []
    for word in shlex.split(run):
        word = fill(word, values)
        matches = sorted(glob.glob(word)) if any(c in word for c in "*?[") else []
        argv.extend(matches or [word])
    if argv[0] in ("uv", "uvx") and local_uv != pinned_uv:
        argv = ["uvx", "--from", f"uv=={pinned_uv}", *argv]
    return argv


def run_pair(table: dict, os_name: str, python: str, version: str) -> bool:
    pinned, local = table["uv"], installed_uv()
    with tempfile.TemporaryDirectory(prefix=f"ghostcrt-checks-{python}-") as tmp:
        values = {
            "dist": f"{tmp}/dist",
            "smoke": f"{tmp}/smoke",
            "python": python,
            "version": version,
        }
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
        env.update(UV_PYTHON=python, UV_PROJECT_ENVIRONMENT=f"{tmp}/venv")
        for step in select(table, os_name, python):
            label = f"[{os_name} / python {python}] {step['name']}"
            if "{purelib}" in step["run"] and "purelib" not in values:
                found = subprocess.run(
                    command(PURELIB, values, local, pinned),
                    cwd=ROOT,
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                values["purelib"] = found.stdout.strip()
            argv = command(step["run"], values, local, pinned)
            cwd = tmp if step.get("cwd") == "tmp" else ROOT
            print(f"==> {label}: {shlex.join(argv)}", flush=True)
            if "expect" in step:
                result = subprocess.run(
                    argv, cwd=cwd, env=env, check=False, capture_output=True, text=True
                )
                sys.stdout.write(result.stdout + result.stderr)
                expected = fill(step["expect"], values)
                ok = result.returncode == 0 and result.stdout.strip() == expected
                if not ok:
                    print(f"expected output: {expected!r}", flush=True)
            else:
                ok = subprocess.run(argv, cwd=cwd, env=env, check=False).returncode == 0
            if not ok:
                print(f"FAILED {label}", flush=True)
                return False
    return True


def tree_is_clean() -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return not status.stdout.strip()


def run_in_docker(table: dict, os_name: str, python: str) -> bool:
    """Run one ubuntu pair in a container built from the committed tree, as a non-root user."""
    if (
        shutil.which("docker") is None
        or subprocess.run(["docker", "info"], check=False, capture_output=True).returncode
    ):
        print(f"FAILED [{os_name} / python {python}]: Docker is not running.", flush=True)
        return False
    image = os_name.replace("-", ":", 1)  # ubuntu-24.04 -> ubuntu:24.04
    user_script = (
        f"curl -LsSf https://astral.sh/uv/{table['uv']}/install.sh | sh >/dev/null && "
        'export PATH="$HOME/.local/bin:$PATH" && cd /work && '
        f"uv run --python {python} --no-project python scripts/checks.py "
        f"--os {os_name} --python {python}"
    )
    root_script = (
        "set -e; apt-get update -qq; "
        "apt-get install -y -qq curl ca-certificates git >/dev/null; "
        "useradd -m checks; mkdir /work; tar -x -C /work; chown -R checks /work; "
        'exec runuser -u checks -- bash -c "$CHECKS"'
    )
    print(f"==> [{os_name} / python {python}] in Docker ({image})", flush=True)
    archive = subprocess.Popen(["git", "archive", "HEAD"], cwd=ROOT, stdout=subprocess.PIPE)
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "-e",
            f"CHECKS={user_script}",
            image,
            "bash",
            "-c",
            root_script,
        ],
        stdin=archive.stdout,
        check=False,
    )
    archive.stdout.close()
    return archive.wait() == 0 and result.returncode == 0


def main(argv: list[str] | None = None) -> int:
    project = load_project()
    table = project["tool"]["ghostcrt"]["checks"]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--os", choices=table["os"], help="CI runner label (default: this machine)")
    parser.add_argument(
        "--python",
        action="append",
        choices=table["python"],
        help="Python version, repeatable (default: every version in the table)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="also run every ubuntu pair in Docker; needs a clean tree (HEAD is what runs there)",
    )
    args = parser.parse_args(argv)
    os_name = args.os or default_os(table)
    pythons = args.python or table["python"]
    version = project["project"]["version"]

    if args.all and not tree_is_clean():
        print("--all checks HEAD in Docker: commit or stash changes first.", file=sys.stderr)
        return 2
    results = {(os_name, py): run_pair(table, os_name, py, version) for py in pythons}
    if args.all:
        for other in (
            name for name in table["os"] if name.startswith("ubuntu") and name != os_name
        ):
            results.update({(other, py): run_in_docker(table, other, py) for py in pythons})

    print("\nSummary")
    for (name, python), ok in results.items():
        print(f"  {'ok    ' if ok else 'FAILED'} {name} / python {python}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
