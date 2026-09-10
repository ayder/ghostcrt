from ghostcrt.__main__ import parse_args


def test_parse_args_defaults():
    ns = parse_args([])
    assert ns.config is None
    assert ns.vault is None
    assert ns.theme is None
    assert ns.debug is False


def test_parse_args_all():
    ns = parse_args(
        ["--config", "/tmp/c", "--vault", "/tmp/v", "--theme", "nord", "--debug"]
    )
    assert str(ns.config) == "/tmp/c"
    assert str(ns.vault) == "/tmp/v"
    assert ns.theme == "nord"
    assert ns.debug is True
