from textual.app import App
from textual.widgets import Input, Static, TextArea

from ghostcrt.models import Host
from ghostcrt.ui.screens.host_edit import HostEditModal


class HostEditApp(App[None]):
    def __init__(self, host: Host | None = None) -> None:
        super().__init__()
        self.host = host

    def on_mount(self) -> None:
        self.push_screen(HostEditModal(self.host, is_new=self.host is None))


async def test_editor_loads_gcp_and_forwarding_options():
    proxy_command = (
        "gcloud compute start-iap-tunnel %h %p --listen-on-stdin "
        "--project=my-project --zone=europe-west1-b"
    )
    host = Host(
        alias="gcp-vm",
        extra={
            "proxycommand": proxy_command,
            "identitiesonly": "yes",
            "userknownhostsfile": "~/.ssh/google_compute_known_hosts",
            "localforward": ["8080 localhost:80", "5432 db:5432"],
            "serveraliveinterval": "30",
        },
    )
    app = HostEditApp(host)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        assert screen.query_one("#proxy-command", Input).value == proxy_command
        assert screen.query_one("#identities-only", Input).value == "yes"
        assert (
            screen.query_one("#known-hosts-file", Input).value
            == "~/.ssh/google_compute_known_hosts"
        )
        assert screen.query_one("#forwarding", TextArea).text == (
            "LocalForward 8080 localhost:80\nLocalForward 5432 db:5432"
        )
        assert (
            screen.query_one("#extra-directives", TextArea).text
            == "serveraliveinterval 30"
        )


async def test_editor_builds_advanced_options_and_repeated_forwards():
    app = HostEditApp()

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.query_one("#aliases", Input).value = "gcp-vm"
        screen.query_one("#hostname", Input).value = "actual-vm-name"
        screen.query_one("#proxy-command", Input).value = (
            "gcloud compute start-iap-tunnel %h %p --listen-on-stdin "
            "--project=my-project --zone=europe-west1-b"
        )
        screen.query_one("#control-master", Input).value = "auto"
        screen.query_one("#control-path", Input).value = "~/.ssh/sockets/%r@%h:%p"
        screen.query_one("#control-persist", Input).value = "10m"
        screen.query_one("#forwarding", TextArea).text = (
            "LocalForward 8080 localhost:80\n"
            "LocalForward 5432 database.internal:5432\n"
            "DynamicForward 1080"
        )
        screen.query_one("#extra-directives", TextArea).text = (
            "ServerAliveInterval 30\nServerAliveCountMax=3"
        )

        host = screen._build_host()

        assert host is not None
        assert host.extra["localforward"] == [
            "8080 localhost:80",
            "5432 database.internal:5432",
        ]
        assert host.extra["dynamicforward"] == "1080"
        assert host.extra["controlmaster"] == "auto"
        assert host.extra["serveraliveinterval"] == "30"
        assert host.extra["serveralivecountmax"] == "3"


async def test_editor_rejects_non_forward_directive_in_forwarding_section():
    app = HostEditApp()

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.query_one("#aliases", Input).value = "bad-forward"
        screen.query_one("#forwarding", TextArea).text = "ProxyCommand command"

        assert screen._build_host() is None
        assert "forwarding must use" in str(screen.query_one("#host-edit-error", Static).content)
