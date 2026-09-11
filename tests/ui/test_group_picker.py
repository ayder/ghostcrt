from textual.app import App
from textual.widgets import Button, Input, OptionList, Static

from ghostcrt.ui.screens.group_picker import GroupPickerScreen


class TestGroupPicker:
    async def test_create_with_highlighted_group_and_empty_box_returns_it(self):
        chosen: list[str | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(GroupPickerScreen(["production", "staging"]), chosen.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#group-options", OptionList)
            options.highlighted = 1
            await pilot.pause()
            await pilot.click("#create")
            await pilot.pause()

        assert chosen == ["staging"]

    async def test_create_with_nothing_highlighted_and_empty_box_stays_open(self):
        chosen: list[str | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(GroupPickerScreen(["production"]), chosen.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#group-options", OptionList)
            assert options.highlighted is None

            picker_screen = app.screen
            await pilot.click("#create")
            await pilot.pause()

            assert chosen == []
            assert app.screen is picker_screen
            error = app.screen.query_one("#group-picker-error", Static)
            assert error.content == "Choose a group or type a new name."

    async def test_typed_existing_name_returns_it(self):
        chosen: list[str | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(GroupPickerScreen(["production"]), chosen.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#new-group", Input).value = "production"
            await pilot.click("#create")
            await pilot.pause()

        assert chosen == ["production"]

    async def test_typed_name_wins_over_highlight(self):
        chosen: list[str | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(GroupPickerScreen(["production", "staging"]), chosen.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#group-options", OptionList)
            options.highlighted = 1
            app.screen.query_one("#new-group", Input).value = "brand-new"
            await pilot.pause()
            await pilot.click("#create")
            await pilot.pause()

        assert chosen == ["brand-new"]

    async def test_button_label_follows_state(self):
        chosen: list[str | None] = []

        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(GroupPickerScreen(["production"]), chosen.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            button = app.screen.query_one("#create", Button)
            assert button.label == "Choose"

            app.screen.query_one("#new-group", Input).value = "x"
            await pilot.pause()
            assert button.label == "Create"

            app.screen.query_one("#new-group", Input).value = ""
            await pilot.pause()
            assert button.label == "Choose"
