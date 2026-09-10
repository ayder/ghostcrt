from ghostcrt.models import SessionState
from ghostcrt.ui.widgets.session_tabs import tab_title


def test_tab_title_connected():
    assert tab_title("web", SessionState.CONNECTED, None) == "web"


def test_tab_title_disconnected():
    assert tab_title("web", SessionState.DISCONNECTED, 1) == "web [exit 1]"
