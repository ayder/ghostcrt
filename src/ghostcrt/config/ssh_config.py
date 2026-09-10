from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from pathlib import Path

from sshconf import empty_ssh_config_file, read_ssh_config_file

from ghostcrt.models import Host, SshOptionValue

_KNOWN = {
    "hostname": "hostname",
    "user": "user",
    "port": "port",
    "identityfile": "identity_file",
}


class SshConfigError(Exception):
    """Raised when ~/.ssh/config cannot be parsed or written."""


def is_concrete_alias(token: str) -> bool:
    return (
        bool(token)
        and not token.startswith("-")
        and not any(c in token for c in "*?!")
        and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)
    )


def _split_host_keys(host_key: str) -> list[str]:
    return [t for t in host_key.split() if t]


def _host_key_for_aliases(aliases: list[str]) -> str:
    return " ".join(aliases)


def _first(value) -> str | None:
    """Return the first element if sshconf gives a list (duplicate keys), else the value."""
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value)


def _option_value(value) -> SshOptionValue:
    """Keep repeated SSH directives as a list instead of discarding all but one."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return str(value)


def _params_to_host(alias: str, aliases: list[str], params: dict) -> Host:
    hostname = _first(params.get("hostname"))
    user = _first(params.get("user"))
    port_raw = _first(params.get("port"))
    port: int | None
    if port_raw is None:
        port = None
    else:
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            port = None
    identity = params.get("identityfile")
    identity_file = _option_value(identity) if identity is not None else None
    extra: dict[str, SshOptionValue] = {}
    for k, v in params.items():
        if k in _KNOWN:
            continue
        extra[k] = _option_value(v)
    return Host(
        alias=alias,
        aliases=list(aliases),
        hostname=hostname,
        user=user,
        port=port,
        identity_file=identity_file,
        extra=extra,
    )


def _host_to_kwargs(host: Host) -> dict[str, SshOptionValue]:
    kwargs: dict[str, SshOptionValue] = {}
    if host.hostname is not None:
        kwargs["Hostname"] = host.hostname
    if host.user is not None:
        kwargs["User"] = host.user
    if host.port is not None:
        kwargs["Port"] = str(host.port)
    if host.identity_file is not None:
        kwargs["IdentityFile"] = host.identity_file
    for k, v in host.extra.items():
        # sshconf accepts arbitrary keys; capitalize common ones if lowercase
        key = k if k[:1].isupper() else k.capitalize()
        kwargs[key] = v
    return kwargs


class SshConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._config = None
        self.reload()

    def reload(self) -> None:
        try:
            if not self.path.is_file():
                self._config = empty_ssh_config_file()
            else:
                self._config = read_ssh_config_file(str(self.path))
            self._saved_config = deepcopy(self._config)
        except Exception as exc:  # sshconf raises various errors
            raise SshConfigError(f"failed to parse {self.path}: {exc}") from exc

    def _find_host_key(self, alias: str) -> str | None:
        assert self._config is not None
        for host_key in self._config.hosts():
            tokens = _split_host_keys(host_key)
            if alias in tokens:
                return host_key
        return None

    def hosts(self) -> list[Host]:
        assert self._config is not None
        rows: list[Host] = []
        seen: set[str] = set()
        for host_key in self._config.hosts():
            tokens = _split_host_keys(host_key)
            if not any(is_concrete_alias(t) for t in tokens):
                continue
            params = self._config.host(host_key) or {}
            for token in tokens:
                if not is_concrete_alias(token):
                    continue
                if token in seen:
                    continue
                seen.add(token)
                rows.append(_params_to_host(token, tokens, params))
        return rows

    def patterns(self) -> list[Host]:
        """Wildcard stanzas. These are settings that apply to matching hosts,
        not destinations you can connect to."""
        assert self._config is not None
        rows: list[Host] = []
        seen: set[str] = set()
        for host_key in self._config.hosts():
            tokens = _split_host_keys(host_key)
            params = self._config.host(host_key) or {}
            for token in tokens:
                if is_concrete_alias(token) or token in seen:
                    continue
                seen.add(token)
                rows.append(_params_to_host(token, tokens, params))
        return rows

    def get(self, alias: str) -> Host | None:
        for h in self.hosts():
            if h.alias == alias:
                return h
        return None

    def add(self, host: Host) -> None:
        assert self._config is not None
        aliases = host.aliases or [host.alias]
        key = _host_key_for_aliases(aliases)
        if self._find_host_key(host.alias) is not None:
            raise SshConfigError(f"host alias already exists: {host.alias}")
        # ensure none of the aliases collide
        for a in aliases:
            if self._find_host_key(a) is not None:
                raise SshConfigError(f"host alias already exists: {a}")
        candidate = deepcopy(self._config)
        candidate.add(key, **deepcopy(_host_to_kwargs(host)))
        self._config = candidate

    def update(self, alias: str, host: Host) -> None:
        assert self._config is not None
        old_key = self._find_host_key(alias)
        if old_key is None:
            raise SshConfigError(f"host not found: {alias}")
        aliases = host.aliases or [host.alias]
        new_key = _host_key_for_aliases(aliases)
        # Validate before changing anything, including the in-memory store.
        for a in aliases:
            other = self._find_host_key(a)
            if other is not None and other != old_key:
                raise SshConfigError(f"host alias already exists: {a}")
        candidate = deepcopy(self._config)
        # Keep this stanza in place: moving it past wildcard defaults changes SSH semantics.
        if new_key != old_key:
            candidate.rename(old_key, new_key)
        options = _host_to_kwargs(host)
        for key in candidate.host(new_key) or {}:
            candidate.set(new_key, **{key: []})
        # sshconf consumes list values in reverse; pass reversed copies to preserve order.
        candidate.set(
            new_key,
            **{
                key: list(reversed(value)) if isinstance(value, list) else value
                for key, value in options.items()
            },
        )
        self._config = candidate

    def delete(self, alias: str) -> None:
        assert self._config is not None
        key = self._find_host_key(alias)
        if key is None:
            raise SshConfigError(f"host not found: {alias}")
        self._config.remove(key)

    def save(self) -> None:
        assert self._config is not None
        tmp: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, prefix=".ghostcrt-", delete=False
            ) as f:
                tmp = Path(f.name)
            self._config.write(str(tmp))
            os.replace(tmp, self.path)
        except OSError as exc:
            self._config = deepcopy(self._saved_config)
            raise SshConfigError("Unable to save SSH configuration.") from exc
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        self._saved_config = deepcopy(self._config)
