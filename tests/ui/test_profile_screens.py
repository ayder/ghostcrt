import importlib

import pytest
from textual.app import App
from textual.widgets import Button, OptionList, Static

from ghostcrt.ui.screens.profile_edit import ProfileEditModal
from ghostcrt.ui.screens.profile_picker import ProfilePick, ProfilePickerScreen


class TestVaultEditRemoved:
    def test_module_is_gone(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("ghostcrt.ui.screens.vault_edit")


def _error_text(screen):
    return str(screen.query_one("#profile-edit-error", Static).content)


async def _press(pilot, button_id):
    # Button.press() bypasses the mouse-click guard that ignores a second
    # pilot.click() landing inside the button's ~0.2s "-active" press effect,
    # which is far longer than a test's back-to-back presses take.
    pilot.app.screen.query_one(button_id, Button).press()
    await pilot.pause()


class TestProfileEditModal:
    @pytest.mark.parametrize(
        ("profile_id", "password", "message"),
        [
            ("", "p", "Profile id cannot be empty."),
            ("x" * 65, "p", "Profile id is too long or contains control characters."),
            ("a\x01", "p", "Profile id is too long or contains control characters."),
            ("ops", "", "Password cannot be empty."),
        ],
    )
    async def test_validation_messages_keep_modal_open(self, profile_id, password, message):
        results: list[tuple[str, str] | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfileEditModal(profiles=[]), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#profile-id").value = profile_id
            screen.query_one("#password").value = password
            await pilot.pause()
            await _press(pilot, "#save")

            assert _error_text(screen) == message
            assert app.screen is screen
            assert results == []

    async def test_new_profile_saves_on_first_press(self):
        results: list[tuple[str, str] | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfileEditModal(profiles=["other"]), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#profile-id").value = "ops"
            screen.query_one("#password").value = "s3"
            await pilot.pause()
            await _press(pilot, "#save")

        assert results == [("ops", "s3")]

    async def test_same_id_warns_then_saves(self):
        results: list[tuple[str, str] | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfileEditModal(profiles=["ops"]), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#profile-id").value = "ops"
            screen.query_one("#password").value = "s3"
            await pilot.pause()

            await _press(pilot, "#save")
            assert _error_text(screen) == "Existing profile: password will be replaced."
            assert app.screen is screen
            assert results == []

            await _press(pilot, "#save")
            assert results == [("ops", "s3")]

    async def test_changed_id_warns_again(self):
        results: list[tuple[str, str] | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfileEditModal(profiles=["ops", "db"]), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#password").value = "s3"
            await pilot.pause()

            screen.query_one("#profile-id").value = "ops"
            await pilot.pause()
            await _press(pilot, "#save")
            assert _error_text(screen) == "Existing profile: password will be replaced."
            assert results == []

            screen.query_one("#profile-id").value = "db"
            await pilot.pause()
            await _press(pilot, "#save")
            assert _error_text(screen) == "Existing profile: password will be replaced."
            assert app.screen is screen
            assert results == []

            await _press(pilot, "#save")
            assert results == [("db", "s3")]

    async def test_password_error_does_not_rearm_and_id_is_stripped(self):
        results: list[tuple[str, str] | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfileEditModal(profiles=["ops"]), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#profile-id").value = " ops "
            screen.query_one("#password").value = "s3"
            await pilot.pause()
            await _press(pilot, "#save")
            assert _error_text(screen) == "Existing profile: password will be replaced."
            assert results == []

            screen.query_one("#password").value = ""
            await pilot.pause()
            await _press(pilot, "#save")
            assert _error_text(screen) == "Password cannot be empty."
            assert app.screen is screen
            assert results == []

            screen.query_one("#password").value = "s3"
            await pilot.pause()
            await _press(pilot, "#save")
            assert results == [("ops", "s3")]

    async def test_editing_the_id_text_forgets_the_warning(self):
        results: list[tuple[str, str] | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfileEditModal(profiles=["ops"]), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one("#profile-id").value = "ops"
            screen.query_one("#password").value = "s3"
            await pilot.pause()
            await _press(pilot, "#save")
            assert _error_text(screen) == "Existing profile: password will be replaced."
            assert app.screen is screen
            assert results == []

            # Same stripped id ("ops"), but the input's text itself changed
            # (trailing space added): the warning must be forgotten and
            # re-armed, not carried over because the normalized id matches.
            screen.query_one("#profile-id").value = "ops "
            await pilot.pause()
            await _press(pilot, "#save")
            assert _error_text(screen) == "Existing profile: password will be replaced."
            assert app.screen is screen
            assert results == []

            await _press(pilot, "#save")
            assert results == [("ops", "s3")]


class TestProfilePicker:
    async def test_options_and_result_object(self):
        # allow_none=True: (none) plus each profile, selecting (none).
        results: list[ProfilePick | None] = []

        class NoneApp(App[None]):
            def on_mount(self):
                self.push_screen(
                    ProfilePickerScreen("Assign", ["a", "b"], allow_none=True),
                    results.append,
                )

        app = NoneApp()
        async with app.run_test() as pilot:
            options = app.screen.query_one("#profile-options", OptionList)
            ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
            prompts = [
                str(options.get_option_at_index(i).prompt) for i in range(options.option_count)
            ]
            assert ids == ["none", "profile:a", "profile:b"]
            assert [prompt.strip() for prompt in prompts] == ["(none)", "a", "b"]

            options.highlighted = 0
            options.action_select()
            await pilot.pause()

        assert results == [ProfilePick(None)]

        # No allow_none: only the profiles, selecting an existing entry.
        results.clear()

        class DeleteApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfilePickerScreen("Delete", ["a", "b"]), results.append)

        app = DeleteApp()
        async with app.run_test() as pilot:
            options = app.screen.query_one("#profile-options", OptionList)
            ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
            assert ids == ["profile:a", "profile:b"]

            options.highlighted = 1
            options.action_select()
            await pilot.pause()

        assert results == [ProfilePick("b")]

        # Cancel dismisses None.
        results.clear()

        class CancelApp(App[None]):
            def on_mount(self):
                self.push_screen(ProfilePickerScreen("Delete", ["a", "b"]), results.append)

        app = CancelApp()
        async with app.run_test() as pilot:
            await _press(pilot, "#cancel")

        assert results == [None]
