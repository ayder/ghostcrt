from pathlib import Path

import pytest
from ghostcrt.ui.screens.snippet_edit import SnippetEdit, SnippetEditModal
from ghostcrt.ui.screens.snippet_picker import SnippetPickerScreen
from textual.app import App
from textual.widgets import Button, Input, OptionList, Static, TextArea

from ghostcrt.config.inventory import HostInventory
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.snippet_bar import SnippetBar, SnippetButton
from ghostcrt.vault.snippets import Snippet
from ghostcrt.vault.vault import Vault, VaultError


def modal_app(screen, results):
    class ModalApp(App[None]):
        def on_mount(self):
            self.push_screen(screen, results.append)

    return ModalApp()


async def press(pilot, button_id):
    # Button.press() avoids pilot.click's ~0.2s guard against a second click.
    pilot.app.screen.query_one(button_id, Button).press()
    await pilot.pause()


def error_text(screen) -> str:
    return str(screen.query_one("#snippet-edit-error", Static).content)


class TestSnippetPicker:
    async def test_lists_all_slots_and_returns_the_chosen_one(self):
        results = []
        app = modal_app(SnippetPickerScreen([Snippet(1, "sudo", "x"), Snippet(4, "psql", "y")]), results)
        async with app.run_test() as pilot:
            options = app.screen.query_one(OptionList)
            prompts = [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]
            assert [p.strip().removeprefix("> ") for p in prompts] == [
                "1  sudo",
                "2  (empty)",
                "3  (empty)",
                "4  psql",
                "5  (empty)",
            ]

            await pilot.press("down", "enter")
            await pilot.pause()

        assert results == [2]

    async def test_escape_cancels(self):
        results = []
        app = modal_app(SnippetPickerScreen([]), results)
        async with app.run_test() as pilot:
            await pilot.press("escape")
            await pilot.pause()

        assert results == [None]


class TestSnippetEditModal:
    async def test_save_returns_the_edit_with_newlines_normalized(self):
        results = []
        app = modal_app(SnippetEditModal(2, None), results)
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#snippet-name", Input).value = "  sudo  "
            screen.query_one("#snippet-text", TextArea).text = "line1\r\nline2\\n"
            await pilot.pause()
            await press(pilot, "#save")

        assert results == [SnippetEdit(2, "sudo", "line1\nline2\\n")]

    async def test_existing_snippet_is_loaded(self):
        results = []
        app = modal_app(SnippetEditModal(1, Snippet(1, "sudo", "pw\\n")), results)
        async with app.run_test():
            screen = app.screen
            assert screen.query_one("#snippet-name", Input).value == "sudo"
            assert screen.query_one("#snippet-text", TextArea).text == "pw\\n"
            assert not screen.query_one("#delete", Button).disabled

    @pytest.mark.parametrize(
        ("name", "text", "message"),
        [
            ("", "pw", "Name cannot be empty."),
            ("a\x01", "pw", "Name is too long or contains control characters."),
            ("sudo", "", "Text cannot be empty."),
            ("sudo", "x" * 4097, "Text is longer than 4096 characters."),
            ("sudo", "a\x07", "Text contains control characters."),
        ],
    )
    async def test_validation_messages_keep_modal_open(self, name, text, message):
        results = []
        app = modal_app(SnippetEditModal(1, None), results)
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#snippet-name", Input).value = name
            screen.query_one("#snippet-text", TextArea).text = text
            await pilot.pause()
            await press(pilot, "#save")

            assert error_text(screen) == message
            assert app.screen is screen
        assert results == []

    async def test_delete_is_disabled_for_an_empty_slot(self):
        app = modal_app(SnippetEditModal(3, None), [])
        async with app.run_test():
            assert app.screen.query_one("#delete", Button).disabled

    async def test_delete_needs_two_presses(self):
        results = []
        app = modal_app(SnippetEditModal(1, Snippet(1, "sudo", "pw")), results)
        async with app.run_test() as pilot:
            screen = app.screen
            await press(pilot, "#delete")
            assert error_text(screen) == "Press Delete again to remove snippet 1."
            assert results == []

            await press(pilot, "#delete")

        assert results == [SnippetEdit(1, "sudo", None)]

    async def test_editing_disarms_delete(self):
        results = []
        app = modal_app(SnippetEditModal(1, Snippet(1, "sudo", "pw")), results)
        async with app.run_test() as pilot:
            screen = app.screen
            await press(pilot, "#delete")
            screen.query_one("#snippet-name", Input).value = "sudo2"
            await pilot.pause()
            assert error_text(screen) == ""

            await press(pilot, "#delete")
            assert error_text(screen) == "Press Delete again to remove snippet 1."
            assert results == []

    async def test_escape_from_text_box_cancels(self):
        results = []
        app = modal_app(SnippetEditModal(1, None), results)
        async with app.run_test() as pilot:
            app.screen.query_one("#snippet-text", TextArea).focus()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert results == [None]

    async def test_enter_in_text_box_inserts_a_newline(self):
        results = []
        app = modal_app(SnippetEditModal(1, None), results)
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#snippet-name", Input).value = "two"
            area = screen.query_one("#snippet-text", TextArea)
            area.focus()
            await pilot.press("a", "enter", "b")
            await press(pilot, "#save")

        assert results == [SnippetEdit(1, "two", "a\nb")]


def vault_app(tmp_path):
    includes = tmp_path / "includes"
    includes.mkdir()
    (includes / "production.conf").write_text("Host web01\n")
    config = tmp_path / "config"
    config.write_text(f"Include {includes}/*\n")
    vault = Vault.create(tmp_path / "vault.enc", "synthetic-master")

    class VaultApp(App[None]):
        CSS_PATH = str(Path(__file__).parents[2] / "src/ghostcrt/ui/compact.tcss")

        def on_mount(self):
            self.main_screen = MainScreen(vault, HostInventory(config, includes))
            self.push_screen(self.main_screen)

    return VaultApp(), vault


def record_notifications(screen):
    calls = []

    def fake_notify(message, *, title="", severity="information", timeout=None, markup=True):
        calls.append((message, severity))

    screen.notify = fake_notify
    return calls


def bar_labels(screen) -> list[str]:
    bar = screen.query_one(SnippetBar)
    return [str(b.label) for b in bar.query(SnippetButton) if b.display]


class TestVaultMenuSnippets:
    async def test_save_and_delete_through_the_menu(self, tmp_path):
        app, vault = vault_app(tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            screen = app.main_screen
            notes = record_notifications(screen)

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("snippets")
            await pilot.pause()
            assert isinstance(app.screen, SnippetPickerScreen)
            app.screen.dismiss(2)
            await pilot.pause()
            assert isinstance(app.screen, SnippetEditModal)
            app.screen.dismiss(SnippetEdit(2, "sudo", "synthetic-pw\\n"))
            await pilot.pause()

            assert vault.get_snippet(2) == Snippet(2, "sudo", "synthetic-pw\\n")
            assert ("Saved snippet 2", "information") in notes
            assert bar_labels(screen) == ["2 sudo"]
            assert not any("synthetic-pw" in message for message, _ in notes)

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("snippets")
            await pilot.pause()
            app.screen.dismiss(2)
            await pilot.pause()
            assert app.screen.query_one("#snippet-name", Input).value == "sudo"
            app.screen.dismiss(SnippetEdit(2, "sudo", None))
            await pilot.pause()

            assert vault.get_snippet(2) is None
            assert ("Deleted snippet 2", "information") in notes
            assert bar_labels(screen) == []

        assert Vault.unlock(vault.path, "synthetic-master").snippets() == []

    async def test_failed_save_reports_error_and_keeps_bar(self, tmp_path, monkeypatch):
        app, vault = vault_app(tmp_path)
        vault.update_snippet(1, "sudo", "old")
        async with app.run_test(size=(120, 30)) as pilot:
            screen = app.main_screen
            notes = record_notifications(screen)

            def disk_full(*args, **kwargs):
                raise VaultError("Unable to save vault. Check disk space and permissions.")

            monkeypatch.setattr(vault, "update_snippet", disk_full)

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("snippets")
            await pilot.pause()
            app.screen.dismiss(1)
            await pilot.pause()
            app.screen.dismiss(SnippetEdit(1, "renamed", "new"))
            await pilot.pause()

            assert (
                "Unable to save vault. Check disk space and permissions.",
                "error",
            ) in notes
            assert bar_labels(screen) == ["1 sudo"]
