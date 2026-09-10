from ghostcrt.models import AppSettings, Host, Secret, SessionState


def test_host_defaults_aliases_to_alias():
    h = Host(alias="db")
    assert h.aliases == ["db"]
    assert h.hostname is None


def test_host_multi_alias():
    h = Host(alias="primary-db", aliases=["db", "primary-db"], hostname="10.0.0.1")
    assert h.alias == "primary-db"
    assert h.aliases == ["db", "primary-db"]


def test_secret_repr_hides_password():
    s = Secret(alias="db", password="s3cret")
    r = repr(s)
    assert "s3cret" not in r
    assert "db" in r


def test_app_settings_defaults():
    s = AppSettings()
    assert s.theme == "ansi-dark"
    assert s.layout_preset == "default"


def test_session_state_values():
    assert SessionState.CONNECTING.name == "CONNECTING"
    assert SessionState.CONNECTED.name == "CONNECTED"
    assert SessionState.DISCONNECTED.name == "DISCONNECTED"
