import pytest
from textual.app import App
from textual.widgets import Input, Select, Static, TextArea
from textual.widgets._select import SelectOverlay

from ghostcrt.models import Host
from ghostcrt.ui.screens.host_edit import HostEditModal, HostEditResult


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


class TestHostEditProfile:
    @pytest.mark.parametrize(
        ("profiles", "profile"),
        [
            (["ops", "db"], "db"),
            (["ops", "db"], None),
            (["ops", "db"], "gone"),
            ([], None),
        ],
    )
    async def test_select_lists_profiles_and_preselects_current(self, profiles, profile):
        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(
                    HostEditModal(Host(alias="srv1"), profiles=profiles, profile=profile)
                )

        app = TestApp()
        async with app.run_test(size=(120, 40)):
            select = app.screen.query_one("#vault-profile", Select)
            overlay = select.query_one(SelectOverlay)
            prompts = [
                str(overlay.get_option_at_index(i).prompt) for i in range(overlay.option_count)
            ]
            assert prompts == ["(none)", *profiles]
            if profile in profiles:
                assert select.value == profile
            else:
                assert select.is_blank()

    async def test_save_returns_chosen_profile(self):
        results: list[HostEditResult | str | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(
                    HostEditModal(Host(alias="srv1"), profiles=["ops"]), results.append
                )

        # Case A: a profile is chosen.
        app = TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app.screen.query_one("#aliases", Input).value = "srv1"
            app.screen.query_one("#vault-profile", Select).value = "ops"
            await pilot.click("#save")
            await pilot.pause()

        assert isinstance(results[-1], HostEditResult)
        assert results[-1].host.alias == "srv1"
        assert results[-1].profile == "ops"

        # Case B: the select is left blank.
        results.clear()
        app = TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app.screen.query_one("#aliases", Input).value = "srv1"
            await pilot.click("#save")
            await pilot.pause()

        assert isinstance(results[-1], HostEditResult)
        assert results[-1].profile is None
