def test_package_imports():
    import tomllib
    from pathlib import Path

    import ghostcrt

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]
    # The CLI's --version must follow pyproject.toml; 0.2.0 shipped saying 0.1.0.
    assert ghostcrt.__version__ == expected
