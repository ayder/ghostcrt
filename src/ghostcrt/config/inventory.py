from __future__ import annotations

from pathlib import Path

from ghostcrt.config.ssh_config import SshConfigError, SshConfigStore
from ghostcrt.models import Host, HostGroup

READONLY_GROUP = "~/.ssh/config"
GROUP_SUFFIX = ".conf"


class HostInventory:
    """Aggregates one SshConfigStore per group file, plus ~/.ssh/config read-only.

    A group is a file in the includes directory; the group name is the filename
    stem. ghostcrt never writes ~/.ssh/config, so that source is exposed
    read-only.
    """

    def __init__(self, ssh_config: Path, includes: Path) -> None:
        self.ssh_config = ssh_config
        self.includes = includes
        self._groups: list[HostGroup] = []
        self._stores: dict[str, SshConfigStore] = {}
        self.reload()

    def reload(self) -> None:
        self._groups = []
        self._stores = {}
        for path in sorted(self.includes.glob(f"*{GROUP_SUFFIX}")):
            self._groups.append(self._load(path.stem, path, writable=True))
        self._groups.append(self._load(READONLY_GROUP, self.ssh_config, writable=False))
        self._mark_shadowed()

    def _mark_shadowed(self) -> None:
        """ssh takes the first match, and Include sits at the top of
        ~/.ssh/config — so an alias in an earlier group wins over a later one."""
        winner: dict[str, str] = {}
        for group in self._groups:
            for host in group.hosts:
                if host.alias in winner:
                    group.shadowed_by[host.alias] = winner[host.alias]
                else:
                    winner[host.alias] = group.name

    def _load(self, name: str, path: Path, *, writable: bool) -> HostGroup:
        try:
            store = SshConfigStore(path)
            hosts = store.hosts()
            patterns = store.patterns()
        except SshConfigError as exc:
            # One unreadable group must not hide the rest of the inventory.
            return HostGroup(name=name, path=path, writable=writable, error=str(exc))
        self._stores[name] = store
        return HostGroup(
            name=name,
            path=path,
            hosts=hosts,
            patterns=patterns,
            writable=writable,
        )

    def groups(self) -> list[HostGroup]:
        return list(self._groups)

    def hosts(self) -> list[Host]:
        return [host for group in self._groups for host in group.hosts]

    def group_of(self, alias: str) -> str | None:
        for group in self._groups:
            if any(host.alias == alias for host in group.hosts):
                return group.name
        return None

    def is_writable(self, alias: str) -> bool:
        name = self.group_of(alias)
        if name is None:
            return False
        return next(g.writable for g in self._groups if g.name == name)

    def is_group_writable(self, name: str | None) -> bool:
        return any(g.name == name and g.writable and not g.error for g in self._groups)

    # ---- mutation -------------------------------------------------------
    #
    # The stanza is the unit, not the alias: `Host srv1 srv2 srv3` is one block,
    # so deleting or moving srv1 takes srv2 and srv3 with it. Splitting a stanza
    # would silently duplicate its settings.

    def _writable_store(self, group: str) -> SshConfigStore:
        if group == READONLY_GROUP:
            raise SshConfigError(f"{READONLY_GROUP} is read-only")
        store = self._stores.get(group)
        if store is None:
            raise SshConfigError(f"no such group: {group}")
        return store

    def _group_path(self, name: str) -> Path:
        if not name or name != Path(name).name or name in (".", ".."):
            raise SshConfigError(f"invalid group name: {name!r}")
        return self.includes / f"{name}{GROUP_SUFFIX}"

    def _host_in(self, group: str, alias: str) -> Host:
        found = next((g for g in self._groups if g.name == group), None)
        if found is None:
            raise SshConfigError(f"no such group: {group}")
        host = next((h for h in found.hosts if h.alias == alias), None)
        if host is None:
            raise SshConfigError(f"no such host in {group}: {alias}")
        return host

    def add(self, group: str, host: Host) -> None:
        store = self._writable_store(group)
        store.add(host)
        store.save()
        self.reload()

    def update(self, group: str, alias: str, host: Host) -> None:
        store = self._writable_store(group)
        store.update(alias, host)
        store.save()
        self.reload()

    def delete(self, group: str, alias: str) -> None:
        store = self._writable_store(group)
        store.delete(alias)
        store.save()
        self.reload()

    def create_group(self, name: str) -> None:
        path = self._group_path(name)
        if path.exists():
            raise SshConfigError(f"group already exists: {name}")
        self.includes.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text("")
        self.reload()

    def delete_group(self, name: str, *, force: bool = False) -> None:
        path = self._group_path(name)
        group = next((g for g in self._groups if g.name == name), None)
        if group is None:
            raise SshConfigError(f"no such group: {name}")
        if group.hosts and not force:
            raise SshConfigError(f"group is not empty: {name}")
        path.unlink(missing_ok=True)
        self.reload()

    def move(self, alias: str, src: str, dst: str) -> None:
        # Write the destination first. A crash mid-move then duplicates the
        # host, which is visible and recoverable; the reverse order can lose it.
        host = self._host_in(src, alias)
        self.add(dst, host)
        self.delete(src, alias)

    def adopt(self, alias: str, dst: str) -> None:
        """Copy a read-only host into a writable group. The original stays put
        and becomes shadowed."""
        host = self._host_in(READONLY_GROUP, alias)
        self.add(dst, host)
