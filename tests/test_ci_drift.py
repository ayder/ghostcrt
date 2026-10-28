"""CI must run exactly the checks pyproject.toml lists.

The local gate runs the same table through scripts/checks.py, so a green local
gate means a green CI. These tests fail when a workflow drifts from the table.
"""

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNNER = (
    "uv run --no-project python scripts/checks.py "
    "--os ${{ matrix.os }} --python ${{ matrix.python }}"
)


def checks() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ghostcrt"]["checks"]


def workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def setup_uv_steps(name: str) -> list[dict]:
    return [
        step
        for job in workflow(name)["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("astral-sh/setup-uv@")
    ]


def test_ci_matrix_matches_the_checks_table():
    matrix = workflow("ci.yml")["jobs"]["test"]["strategy"]["matrix"]

    assert matrix["os"] == checks()["os"]
    assert [str(version) for version in matrix["python"]] == checks()["python"]


def test_every_workflow_pins_the_checks_uv_version():
    for name in ("ci.yml", "release.yml"):
        steps = setup_uv_steps(name)
        assert steps, name
        assert {step["with"]["version"] for step in steps} == {checks()["uv"]}, name


def test_ci_runs_nothing_but_the_checks_runner():
    job = workflow("ci.yml")["jobs"]["test"]
    runs = [" ".join(step["run"].split()) for step in job["steps"] if "run" in step]

    assert runs == [RUNNER]


def test_release_builds_with_a_checked_python():
    for step in setup_uv_steps("release.yml"):
        assert str(step["with"]["python-version"]) in [*checks()["python"], "${{ matrix.python }}"]


def test_release_runs_the_same_matrix_and_checks_as_ci():
    job = workflow("release.yml")["jobs"]["validate"]
    matrix = job["strategy"]["matrix"]

    assert matrix["os"] == checks()["os"]
    assert [str(version) for version in matrix["python"]] == checks()["python"]
    assert [" ".join(step["run"].split()) for step in job["steps"] if "run" in step] == [RUNNER]


def test_only_the_isolated_pypi_job_has_oidc_permission():
    release = workflow("release.yml")
    jobs = release["jobs"]
    publish = jobs["publish-pypi"]

    assert release["permissions"] == {"contents": "read"}
    assert jobs["build"]["needs"] == "validate"
    assert jobs["release-assets"]["needs"] == "build"
    assert publish["needs"] == "release-assets"
    assert publish["permissions"] == {"id-token": "write"}
    assert publish["environment"]["name"] == "pypi"
    for name, job in jobs.items():
        if name != "publish-pypi":
            assert "id-token" not in job.get("permissions", {})

    # Publishing consumes the build artifact without checking out or running code.
    assert all("run" not in step for step in publish["steps"])
    actions = [step["uses"].split("@")[0] for step in publish["steps"]]
    assert actions == ["actions/download-artifact", "pypa/gh-action-pypi-publish"]
    upload = next(
        step
        for step in jobs["build"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    for job in (jobs["release-assets"], publish):
        download = next(
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/download-artifact@")
        )
        assert download["with"]["name"] == upload["with"]["name"]


def test_check_steps_are_well_formed():
    table = checks()
    names = [step["name"] for step in table["step"]]

    assert len(names) == len(set(names))
    for step in table["step"]:
        assert set(step) <= {"name", "run", "only", "expect", "cwd"}, step["name"]
        assert step.get("cwd", "project") in {"project", "tmp"}, step["name"]
        for key, value in step.get("only", {}).items():
            assert key in {"os", "python"}, step["name"]
            assert value in table[key], step["name"]


def test_lint_ignores_the_ruff_cache():
    # A stale local cache hid an import-order failure that CI then caught (0.4.0).
    lint = next(step for step in checks()["step"] if step["name"] == "lint")

    assert "--no-cache" in lint["run"].split()
