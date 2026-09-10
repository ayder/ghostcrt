from __future__ import annotations

import re
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from ghostcrt.models import Host, SshOptionValue

_ADVANCED_FIELDS = {
    "proxycommand": ("proxy-command", "ProxyCommand"),
    "identitiesonly": ("identities-only", "IdentitiesOnly"),
    "userknownhostsfile": ("known-hosts-file", "UserKnownHostsFile"),
    "controlmaster": ("control-master", "ControlMaster"),
    "controlpath": ("control-path", "ControlPath"),
    "controlpersist": ("control-persist", "ControlPersist"),
}
_FORWARD_DIRECTIVES = {
    "localforward": "LocalForward",
    "remoteforward": "RemoteForward",
    "dynamicforward": "DynamicForward",
}
_FIRST_CLASS_DIRECTIVES = {
    "host",
    "hostname",
    "user",
    "port",
    "identityfile",
    "match",
}
_DIRECTIVE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)(?:\s+|=)(.+?)\s*$")


def _values(value: SshOptionValue) -> list[str]:
    return value if isinstance(value, list) else [value]


def _single_extra(extra: dict[str, SshOptionValue], key: str) -> str:
    value = extra.get(key)
    if value is None:
        return ""
    values = _values(value)
    return values[0] if values else ""


def _add_directive(
    directives: dict[str, SshOptionValue],
    key: str,
    value: str,
) -> None:
    current = directives.get(key)
    if current is None:
        directives[key] = value
    elif isinstance(current, list):
        current.append(value)
    else:
        directives[key] = [current, value]


def _parse_directives(
    text: str,
    *,
    forwarding: bool,
) -> tuple[dict[str, SshOptionValue], str | None]:
    directives: dict[str, SshOptionValue] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _DIRECTIVE_RE.fullmatch(line)
        if match is None:
            return {}, f"Line {line_number}: use 'Directive value'."
        raw_key, value = match.groups()
        key = raw_key.lower()
        if forwarding and key not in _FORWARD_DIRECTIVES:
            return (
                {},
                (
                    f"Line {line_number}: forwarding must use LocalForward, "
                    "RemoteForward, or DynamicForward."
                ),
            )
        if not forwarding and key in _FORWARD_DIRECTIVES:
            return {}, f"Line {line_number}: put forwarding directives in Forwarding."
        if not forwarding and key in _FIRST_CLASS_DIRECTIVES:
            return {}, f"Line {line_number}: edit {raw_key} in its dedicated field."
        if not forwarding and key in _ADVANCED_FIELDS:
            return {}, f"Line {line_number}: edit {raw_key} in its dedicated field."
        _add_directive(directives, key, value)
    return directives, None


def _format_directives(
    extra: dict[str, SshOptionValue],
    *,
    forwarding: bool,
) -> str:
    rows: list[str] = []
    for key, value in extra.items():
        is_forward = key.lower() in _FORWARD_DIRECTIVES
        if is_forward != forwarding or key.lower() in _ADVANCED_FIELDS:
            continue
        display_key = _FORWARD_DIRECTIVES.get(key.lower(), key)
        for item in _values(value):
            rows.append(f"{display_key} {item}")
    return "\n".join(rows)


class HostEditModal(ModalScreen[Host | str | None]):
    """Edit a Host block. Returns Host on save, 'delete' on delete, None on cancel."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Cancel"),
    ]

    DEFAULT_CSS = """
    HostEditModal {
        align: center middle;
    }
    #host-edit-box {
        width: 86;
        height: 90%;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #host-edit-fields {
        height: 1fr;
        scrollbar-gutter: stable;
    }
    #forwarding, #extra-directives, #identity {
        height: 5;
    }
    #host-edit-help {
        color: $text-muted;
        height: auto;
    }
    #host-edit-error {
        color: $error;
        height: auto;
        min-height: 1;
    }
    #host-edit-actions {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, host: Host | None = None, *, is_new: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.host = host
        self.is_new = is_new or host is None

    def compose(self) -> ComposeResult:
        h = self.host
        aliases = " ".join(h.aliases) if h else ""
        extra = h.extra if h else {}
        with Vertical(id="host-edit-box"):
            yield Label("Add host" if self.is_new else "Edit host")
            with VerticalScroll(id="host-edit-fields"):
                yield Label("Aliases (space-separated)")
                yield Input(value=aliases, id="aliases", placeholder="web web1")
                yield Label("HostName")
                yield Input(value=(h.hostname or "") if h else "", id="hostname")
                yield Label("User")
                yield Input(value=(h.user or "") if h else "", id="user")
                yield Label("Port")
                yield Input(value=str(h.port) if h and h.port is not None else "", id="port")
                yield Label("Identity files (one per line)")
                yield TextArea(
                    "\n".join(_values(h.identity_file)) if h and h.identity_file else "",
                    id="identity",
                )
                yield Label("ProxyCommand")
                yield Input(
                    value=_single_extra(extra, "proxycommand"),
                    id="proxy-command",
                    placeholder=(
                        "gcloud compute start-iap-tunnel %h %p --listen-on-stdin "
                        "--project=PROJECT --zone=ZONE"
                    ),
                )
                yield Label("IdentitiesOnly")
                yield Input(
                    value=_single_extra(extra, "identitiesonly"),
                    id="identities-only",
                    placeholder="yes",
                )
                yield Label("UserKnownHostsFile")
                yield Input(
                    value=_single_extra(extra, "userknownhostsfile"),
                    id="known-hosts-file",
                    placeholder="~/.ssh/google_compute_known_hosts",
                )
                yield Label("ControlMaster")
                yield Input(
                    value=_single_extra(extra, "controlmaster"),
                    id="control-master",
                    placeholder="auto",
                )
                yield Label("ControlPath")
                yield Input(
                    value=_single_extra(extra, "controlpath"),
                    id="control-path",
                    placeholder="~/.ssh/sockets/%r@%h:%p",
                )
                yield Label("ControlPersist")
                yield Input(
                    value=_single_extra(extra, "controlpersist"),
                    id="control-persist",
                    placeholder="10m",
                )
                yield Label("Forwarding")
                yield Static(
                    "One LocalForward, RemoteForward, or DynamicForward directive per line.",
                    id="host-edit-help",
                )
                yield TextArea(
                    _format_directives(extra, forwarding=True),
                    id="forwarding",
                )
                yield Label("Additional directives")
                yield Static("One 'Directive value' entry per line.")
                yield TextArea(
                    _format_directives(extra, forwarding=False),
                    id="extra-directives",
                )
            yield Static("", id="host-edit-error")
            with Horizontal(id="host-edit-actions"):
                yield Button("Save", id="save", variant="primary")
                if not self.is_new:
                    yield Button("Delete", id="delete", variant="error")
                yield Button("Cancel", id="cancel")

    def _error(self, msg: str) -> None:
        self.query_one("#host-edit-error", Static).update(msg)

    def _build_host(self) -> Host | None:
        aliases_raw = self.query_one("#aliases", Input).value.strip()
        aliases = [a for a in aliases_raw.split() if a]
        if not aliases:
            self._error("At least one alias is required.")
            return None
        if any(a.startswith("-") or any(ord(c) < 32 or ord(c) == 127 for c in a) for a in aliases):
            self._error("Aliases cannot start with '-' or contain control characters.")
            return None
        port_raw = self.query_one("#port", Input).value.strip()
        port: int | None
        if port_raw:
            try:
                port = int(port_raw)
            except ValueError:
                self._error("Port must be an integer.")
                return None
        else:
            port = None
        hostname = self.query_one("#hostname", Input).value.strip() or None
        user = self.query_one("#user", Input).value.strip() or None
        identities = [
            line.strip()
            for line in self.query_one("#identity", TextArea).text.splitlines()
            if line.strip()
        ]
        identity = identities if len(identities) > 1 else (identities[0] if identities else None)
        extra, error = _parse_directives(
            self.query_one("#extra-directives", TextArea).text,
            forwarding=False,
        )
        if error is not None:
            self._error(error)
            return None
        forwards, error = _parse_directives(
            self.query_one("#forwarding", TextArea).text,
            forwarding=True,
        )
        if error is not None:
            self._error(error)
            return None
        extra.update(forwards)
        for key, (widget_id, _display_name) in _ADVANCED_FIELDS.items():
            value = self.query_one(f"#{widget_id}", Input).value.strip()
            if value:
                extra[key] = value
        return Host(
            alias=aliases[0],
            aliases=aliases,
            hostname=hostname,
            user=user,
            port=port,
            identity_file=identity,
            extra=extra,
        )

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        host = self._build_host()
        if host is not None:
            self.dismiss(host)

    @on(Button.Pressed, "#delete")
    def delete(self) -> None:
        self.dismiss("delete")

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
