from __future__ import annotations

import asyncio
import shutil
from copy import deepcopy
from pathlib import Path
from typing import ClassVar

from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input, Static

from ghostcrt.config.include_bootstrap import include_is_configured
from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.config.ssh_config import SshConfigError
from ghostcrt.models import Host
from ghostcrt.ssh.command import build_ssh_command
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.action_menu import ActionMenuScreen
from ghostcrt.ui.screens.confirm_close import ConfirmCloseScreen
from ghostcrt.ui.screens.group_picker import GroupPickerScreen
from ghostcrt.ui.screens.host_edit import HostEditModal, HostEditResult
from ghostcrt.ui.screens.include_setup import IncludeSetupModal
from ghostcrt.ui.screens.profile_edit import ProfileEditModal
from ghostcrt.ui.screens.profile_picker import ProfilePick, ProfilePickerScreen
from ghostcrt.ui.widgets.host_list import HostList
from ghostcrt.ui.widgets.menu_bar import MenuBar
from ghostcrt.ui.widgets.session_tabs import SessionTabs
from ghostcrt.ui.widgets.terminal import TerminalWidget
from ghostcrt.vault.vault import Vault, VaultError

NO_PROFILES_YET = "No profiles yet. Create one first."
ASSIGNMENT_NOT_SAVED = (
    "Host saved; profile assignment was not. Use Vault → Assign profile to selected host… to retry."
)
NO_GROUP_CHOSEN = "Host not saved: no group chosen."


class MainScreen(Screen):
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        Binding("f10", "focus_menu", "Menu", show=False),
        Binding("escape", "focus_terminal", "Terminal", show=False),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("ctrl+n", "focus_hosts", "Hosts", show=False),
        Binding("ctrl+w", "close_session", "Close session", show=False),
        Binding(
            "ctrl+t",
            "focus_hosts",
            "Release terminal",
            key_display="Ctrl+T",
            show=False,
            priority=True,
        ),
    ]

    DEFAULT_CSS = """
    #main-body {
        height: 1fr;
    }
    MainScreen.compact #main-body {
        layout: vertical;
    }
    MainScreen.compact HostList {
        width: 1fr;
        height: 9;
        border-right: none;
        border-bottom: solid ansi_bright_black;
    }
    """

    def __init__(
        self, vault: Vault, inventory: HostInventory, *, ssh_config: Path | None = None, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.vault = vault
        self.inventory = inventory
        self.ssh_config = ssh_config

    def compose(self) -> ComposeResult:
        yield MenuBar()
        with Horizontal(id="main-body"):
            yield HostList(id="host-list")
            yield SessionTabs(id="session-tabs")
        yield Static("ghostcrt · Ctrl+H Help", id="context-status", markup=False)

    def on_mount(self) -> None:
        self.refresh_hosts()
        self.set_class(self.size.width < 90, "compact")
        self.action_focus_hosts()
        self._offer_include_setup()

    def _offer_include_setup(self) -> None:
        if include_is_configured(self.inventory.ssh_config, self.inventory.includes):
            return

        def handle(added: bool | None) -> None:
            if added:
                self.refresh_hosts()

        self.app.push_screen(
            IncludeSetupModal(self.inventory.ssh_config, self.inventory.includes),
            handle,
        )

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 90, "compact")

    def refresh_hosts(self) -> None:
        try:
            self.inventory.reload()
        except SshConfigError as exc:
            self.notify(str(exc), severity="error")
        self.query_one(HostList).set_groups(self.inventory.groups())

    def action_focus_menu(self) -> None:
        self.query_one("#menu-hosts").focus()

    def action_focus_terminal(self) -> None:
        terminal = self.query_one(SessionTabs).active_terminal
        if terminal is not None:
            self.remove_class("hosts-open")
            terminal.focus()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget is not self.app.focused:
            return
        if isinstance(event.widget, TerminalWidget):
            self.remove_class("hosts-open")
            hint = "TERMINAL  Ctrl+T Hosts · Ctrl+O Mouse"
        elif isinstance(event.widget, Input):
            hint = "FILTER  Down Hosts · Esc Terminal · F10 Menu"
        elif event.widget.id == "host-tree":
            hint = "HOSTS  ↑↓ Navigate · Enter Connect · / Filter · F10 Menu · Esc Terminal"
        else:
            hint = "MENU  Enter Open · Tab Next · Esc Terminal"
        self.query_one("#context-status", Static).update(f"ghostcrt · Ctrl+H Help · {hint}")

    def action_focus_search(self) -> None:
        self.add_class("hosts-open")
        self.query_one(HostList).focus_filter()

    def action_focus_hosts(self) -> None:
        self.add_class("hosts-open")
        self.query_one(HostList).focus_list()

    @on(TerminalWidget.ReleaseFocus)
    def on_terminal_release_focus(self) -> None:
        self.action_focus_hosts()

    def action_close_session(self) -> None:
        self.query_one(SessionTabs).request_close_active()

    @on(HostList.HostSelected)
    def on_host_selected(self, event: HostList.HostSelected) -> None:
        self.open_session(event.host)

    @work
    async def open_session(self, host: Host) -> None:
        password = self.vault.get(host.alias)
        if password and not shutil.which("sshpass"):
            self.notify(
                "sshpass is not installed; required for vault passwords.",
                severity="error",
            )
            return
        cmd = build_ssh_command(host.alias, password, config=self.ssh_config)
        session = SshSession(alias=host.alias)
        tabs = self.query_one(SessionTabs)
        pane_id: str | None = None
        try:
            # Mount and lay out the terminal before spawning SSH. This gives
            # the child its real PTY dimensions from the first instruction,
            # rather than starting at 24x80 and racing a later SIGWINCH.
            pane_id = await tabs.add_session(session)
            await session.start(
                cmd.argv,
                pass_fds=cmd.pass_fds,
                password=cmd.password,
                write_fd=cmd.write_fd,
                read_fd=cmd.read_fd,
            )
        except asyncio.CancelledError:
            if pane_id is not None:
                await tabs.close_session(pane_id)
            await session.close()
            raise
        except Exception as exc:
            cmd.close_pipe()
            if pane_id is not None:
                await tabs.close_session(pane_id)
            await session.close()
            self.notify(f"Failed to start session: {exc}", severity="error")
            return

    @on(MenuBar.HostsAction)
    def on_hosts_menu(self) -> None:
        def handle(action: str | None) -> None:
            if action == "add":
                self._host_add()
            elif action == "edit":
                self._host_edit()
            elif action == "clone":
                self._host_clone()
            elif action == "delete":
                self._host_delete()
            elif action == "copy":
                self._host_copy_to_group()

        self.app.push_screen(
            ActionMenuScreen(
                "Hosts",
                [
                    ("add", "Add host"),
                    ("edit", "Edit selected"),
                    ("clone", "Clone selected…"),
                    ("copy", "Copy to group…"),
                    ("delete", "Delete selected…"),
                ],
                anchor_id="menu-hosts",
                disabled=(
                    {"edit", "delete", "copy", "clone"} if self._selected_host() is None
                    else {"edit", "delete"} if self._is_read_only(self._selected_group())
                    else set()
                ),
            ),
            handle,
        )

    @on(MenuBar.VaultAction)
    def on_vault_menu(self) -> None:
        def handle(action: str | None) -> None:
            if action == "profile":
                self._profile_create()
            elif action == "delete-profile":
                self._profile_delete()
            elif action == "assign":
                self._profile_assign()

        self.app.push_screen(
            ActionMenuScreen(
                "Vault",
                [
                    ("profile", "Create / update profile…"),
                    ("delete-profile", "Delete profile…"),
                    ("assign", "Assign profile to selected host…"),
                ],
                anchor_id="menu-vault",
                disabled={"assign"} if self._selected_host() is None else set(),
            ),
            handle,
        )

    @on(MenuBar.SessionAction)
    def on_session_menu(self) -> None:
        def handle(action: str | None) -> None:
            if action == "reconnect":
                self._reconnect()
            elif action == "close":
                self.action_close_session()

        self.app.push_screen(
            ActionMenuScreen(
                "Session",
                [("reconnect", "Reconnect"), ("close", "Close")],
                anchor_id="menu-session",
                disabled={"reconnect", "close"}
                if self.query_one(SessionTabs).active_session is None else set(),
            ),
            handle,
        )

    def _selected_host(self) -> Host | None:
        return self.query_one(HostList).selected_host

    def _selected_group(self) -> str | None:
        return self.query_one(HostList).selected_group

    def _is_read_only(self, group: str | None) -> bool:
        return not self.inventory.is_group_writable(group)

    def _writable_groups(self) -> list[str]:
        return [g.name for g in self.inventory.groups() if g.writable and not g.error]

    def _pick_group(self, then) -> None:
        """Ask for a destination group, creating it if the name is new."""

        def handle(name: str | None) -> None:
            # None is the only cancel: the picker never answers with "". Say so,
            # because the caller was about to write a host the operator had
            # already filled in, and dropping it in silence looks like a bug.
            if name is None:
                self.notify(NO_GROUP_CHOSEN, severity="warning")
                return
            if name not in self._writable_groups():
                try:
                    self.inventory.create_group(name)
                except SshConfigError as exc:
                    self.notify(str(exc), severity="error")
                    return
            then(name)

        self.app.push_screen(GroupPickerScreen(self._writable_groups()), handle)

    def _host_add(self, template: Host | None = None, profile: str | None = None) -> None:
        def handle(result: HostEditResult | str | None) -> None:
            if not isinstance(result, HostEditResult):
                return

            def write(group: str) -> None:
                try:
                    self.inventory.add(group, result.host)
                    self.refresh_hosts()
                except SshConfigError as exc:
                    self.notify(str(exc), severity="error")
                    return
                if result.profile is None:
                    return
                try:
                    self.vault.update_assignment(result.host.aliases[0], result.profile)
                except VaultError:
                    self.notify(ASSIGNMENT_NOT_SAVED, severity="error")

            self._pick_group(write)

        self.app.push_screen(
            HostEditModal(
                template, is_new=True, profiles=self.vault.profiles(), profile=profile
            ), handle
        )

    def _host_clone(self) -> None:
        host = self._selected_host()
        if host is None:
            self.notify("Select a host first.", severity="warning")
            return
        clone = deepcopy(host)
        aliases = {
            alias
            for group in self.inventory.groups()
            for entry in group.hosts
            for alias in entry.aliases
        }
        base = f"{host.alias}-copy"
        alias = base
        suffix = 2
        while alias in aliases:
            alias = f"{base}-{suffix}"
            suffix += 1
        clone.alias = alias
        clone.aliases = [alias]
        self._host_add(clone, self.vault.profile_for(host.alias))

    def _host_copy_to_group(self) -> None:
        host = self._selected_host()
        if host is None:
            self.notify("Select a host first.", severity="warning")
            return
        source = self._selected_group()
        if source is None:
            return

        def write(group: str) -> None:
            if group == source:
                return
            try:
                if source == READONLY_GROUP:
                    self.inventory.adopt(host.alias, group)
                else:
                    self.inventory.move(host.alias, source, group)
                self.refresh_hosts()
                self.notify(f"{host.alias} → {group}")
            except SshConfigError as exc:
                self.notify(str(exc), severity="error")

        self._pick_group(write)

    def _host_edit(self) -> None:
        host = self._selected_host()
        if host is None:
            self.notify("Select a host first.", severity="warning")
            return
        group = self._selected_group()
        if self._is_read_only(group):
            self.notify(
                f"{host.alias} is defined in {READONLY_GROUP}, which ghostcrt "
                "never writes. Use Copy to group to make it editable.",
                severity="warning",
            )
            return

        selected = host.alias

        def handle(result: HostEditResult | str | None) -> None:
            if result is None:
                return
            if result == "delete":
                self._confirm_host_delete(host, group)
                return
            try:
                if isinstance(result, HostEditResult):
                    self.inventory.update(group, selected, result.host)
                self.refresh_hosts()
            except SshConfigError as exc:
                self.notify(str(exc), severity="error")
                return
            if isinstance(result, HostEditResult):
                self._write_edit_assignment(selected, result)

        self.app.push_screen(
            HostEditModal(
                host,
                profiles=self.vault.profiles(),
                profile=self.vault.profile_for(selected),
            ),
            handle,
        )

    def _write_edit_assignment(self, selected: str, result: HostEditResult) -> None:
        """Persist the edited host's assignment against the alias that was highlighted.

        A rename that drops the highlighted alias moves the assignment to the new
        block's first alias. Those are two writes with no rollback between them:
        if the second fails the old alias is already unassigned, which the notify
        text tells the operator how to repair.
        """
        try:
            if selected in result.host.aliases:
                self.vault.update_assignment(selected, result.profile)
            else:
                self.vault.update_assignment(selected, None)
                self.vault.update_assignment(result.host.aliases[0], result.profile)
        except VaultError:
            self.notify(ASSIGNMENT_NOT_SAVED, severity="error")

    def _host_delete(self) -> None:
        host = self._selected_host()
        if host is None:
            self.notify("Select a host first.", severity="warning")
            return
        group = self._selected_group()
        if self._is_read_only(group):
            self.notify(
                f"{host.alias} is defined in {READONLY_GROUP} and is read-only.",
                severity="warning",
            )
            return
        self._confirm_host_delete(host, group)

    def _confirm_host_delete(self, host: Host, group: str | None) -> None:
        if group is None or self._is_read_only(group):
            return
        alias = host.alias
        details = (
            f"Are you sure you want to delete host {alias}?\n\n"
            f"Group: {group}\n"
            f"Aliases: {' '.join(host.aliases)}\n"
            f"HostName: {host.hostname or '(from SSH config)'}\n"
            f"User: {host.user or '(default)'}   Port: {host.port or 22}\n\n"
            "This removes the entire host configuration block."
        )

        def confirmed(delete: bool) -> None:
            if not delete:
                return
            try:
                self.inventory.delete(group, alias)
                self.refresh_hosts()
                self.notify(f"Deleted host block for {alias}")
            except SshConfigError as exc:
                self.notify(str(exc), severity="error")

        self.app.push_screen(ConfirmCloseScreen(details, confirm_label="OK"), confirmed)

    def _profile_create(self) -> None:
        def handle(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            profile_id, password = result
            try:
                self.vault.update_profile(profile_id, password)
            except VaultError as exc:
                self.notify(str(exc), severity="error")
                return
            self.notify(f"Saved profile {profile_id}")

        self.app.push_screen(ProfileEditModal(self.vault.profiles()), handle)

    def _profile_delete(self) -> None:
        profiles = self.vault.profiles()
        if not profiles:
            self.notify(NO_PROFILES_YET, severity="warning")
            return

        def handle(result: ProfilePick | None) -> None:
            if result is None or result.profile is None:
                return
            try:
                self.vault.update_profile(result.profile, None)
            except VaultError as exc:
                self.notify(str(exc), severity="error")
                return
            self.notify(f"Deleted profile {result.profile}")

        self.app.push_screen(ProfilePickerScreen("Delete profile", profiles), handle)

    def _profile_assign(self) -> None:
        host = self._selected_host()
        if host is None:
            self.notify("Select a host first.", severity="warning")
            return
        alias = host.alias
        profiles = self.vault.profiles()
        # With no profiles there is still something to do when this alias holds a
        # stale assignment: the picker can offer (none) to clear it.
        if not profiles and self.vault.profile_for(alias) is None:
            self.notify(NO_PROFILES_YET, severity="warning")
            return

        def handle(result: ProfilePick | None) -> None:
            if result is None:
                return
            try:
                self.vault.update_assignment(alias, result.profile)
            except VaultError as exc:
                self.notify(str(exc), severity="error")
                return
            if result.profile is None:
                self.notify(f"Removed profile from {alias}")
            else:
                self.notify(f"Assigned {result.profile} to {alias}")

        self.app.push_screen(
            ProfilePickerScreen("Assign profile", profiles, allow_none=True), handle
        )

    @work
    async def _reconnect(self) -> None:
        tabs = self.query_one(SessionTabs)
        session = tabs.active_session
        terminal = tabs.active_terminal
        if session is None or terminal is None:
            self.notify("No active session.", severity="warning")
            return
        password = self.vault.get(session.alias)
        if password and not shutil.which("sshpass"):
            self.notify("sshpass is not installed.", severity="error")
            return
        cmd = build_ssh_command(session.alias, password, config=self.ssh_config)
        try:
            await session.reconnect(
                cmd.argv,
                pass_fds=cmd.pass_fds,
                password=cmd.password,
                write_fd=cmd.write_fd,
                read_fd=cmd.read_fd,
                before_start=terminal.reset_session,
            )
        except Exception as exc:
            cmd.close_pipe()
            self.notify(f"Reconnect failed: {exc}", severity="error")
