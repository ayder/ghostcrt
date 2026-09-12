# ghostcrt

Modern terminal UI for managing multiple SSH sessions with an encrypted
password vault. Inspired by tools like `lazyssh`.

Licensed under [GNU GPLv3](LICENSE) (GPL-3.0-only).

## Features (v1)

- Inventory from `~/.ssh/config` **and** `~/.config/ghostcrt/includes/`,
  grouped as a tree (sidebar + fuzzy filter)
- Live interactive SSH sessions in tabs (real `ssh` binary in a PTY)
- Ghostty terminal emulation, scrollback, and input handling via
  [`ghostty-textual`](https://github.com/ayder/ghostty-textual)
- Encrypted local vault for SSH passwords (Argon2id + AES-256-GCM)
- Password delivery via `sshpass -d` (never in argv / env / disk)
- In-app host config and vault management
- Password profiles: store a password once under a profile id and pick it per
  host from a dropdown
- Textual built-in themes (`Ctrl+P`), applied to both the UI and terminal palette

## System dependencies

- OpenSSH client (`ssh`)
- `sshpass` (required only when connecting with a vault password)

macOS: `brew install hudochenkov/sshpass/sshpass` (or your preferred tap)

## Install

```bash
uv tool install https://github.com/ayder/ghostcrt/releases/download/v0.2.1/ghostcrt-0.2.1-py3-none-any.whl
ghostcrt
```

## Develop

Requires Python 3.12+ on macOS 13+ or glibc Linux 2.27+, on x86_64 or ARM64.
The dependency is pinned to the published
[`ghostty-textual` v0.0.2 wheel](https://github.com/ayder/ghostty-textual/releases/tag/v0.0.2)
on GitHub; `uv sync` installs it and the bundled native library automatically.

```bash
git clone https://github.com/ayder/ghostcrt.git
cd ghostcrt
uv sync --all-extras
uv run pytest
uv run ghostcrt
```

## CLI

```bash
ghostcrt [--config PATH] [--vault PATH] [--theme NAME] [--debug] [-h] [--version]
```

| Flag | Meaning |
|------|---------|
| `--config` | SSH config file (default `~/.ssh/config`) |
| `--vault` | Vault file path (default `~/.config/ghostcrt/vault.enc`) |
| `--theme` | Textual theme id (persisted if valid) |
| `--debug` | Debug logging to stderr (never logs secrets) |

## Keys

| Key | Action |
|-----|--------|
| `Ctrl+P` | Command palette (themes, etc.) |
| `Ctrl+H` | Show keyboard help |
| `Ctrl+O` | Toggle mouse capture / native terminal selection |
| `Ctrl+]` | Release terminal focus and return to the host list |
| `Ctrl+N` | Focus host list |
| `/` | Focus host filter |
| `Ctrl+W` | Close active session |
| `Ctrl+Q` / `Esc` (unlock) | Quit |
| `Shift+PageUp/Down` | Scroll local terminal history |
| Mouse wheel | Scroll local terminal history |
| Right-hand scrollbar | Drag to scroll history; click the track to page |
| Mouse drag | Select text to copy |

Click a tab's **×** to close that session. Exited sessions close immediately;
running or connecting sessions ask for confirmation. `Ctrl+W` and Session → Close
use the same confirmation. `Ctrl+Q` asks before disconnecting any live sessions.

Multiline paste is supported. When the remote application enables bracketed
paste, the text is sent as a single paste block. Otherwise, line breaks are sent
as Enter presses, so pasted shell commands may execute immediately.

Mouse reporting is never forwarded to the remote host. Full-screen programs
(Vim, htop, tmux) may still request it — `set mouse=a` and friends are simply
ignored — so the wheel and text selection always belong to the pane. Use
`Shift+PageUp/Down`, the wheel, or the pane's right-hand scrollbar for scrollback.
On macOS, use `Ctrl+O` to
release mouse capture to the host terminal for native selection, and press it
again to restore ghostcrt mouse handling.

## Groups

A group is a file in `~/.config/ghostcrt/includes/`. The filename is the
group name, so `production.conf` becomes the group `production`.

```
~/.config/ghostcrt/includes/
  production.conf     Host srv1 srv2 srv3
                          User jorn
  staging.conf        Host srv4 srv5 srv6
                          User jornv
```

ghostcrt never writes `~/.ssh/config`. It needs one line at the top:

    Include ~/.config/ghostcrt/includes/*.conf

On first run it offers to add that line for you, backing the file up to
`~/.ssh/config.bak` first. The line must be at the **top** — ssh takes the
first value it finds for each keyword, so an `Include` below a `Host *` block
would be shadowed.

Hosts defined in `~/.ssh/config` stay visible and connectable but are
read-only, marked `🔒`. Use **Hosts → Copy to group…** to adopt one into a
group, where it becomes editable. Because the include is read first, the copy
wins; the original is marked `⊘ <group>` to show it has been shadowed.

### Advanced host settings

The host editor includes optional fields for `ProxyCommand`, `IdentitiesOnly`,
`UserKnownHostsFile`, `ControlMaster`, `ControlPath`, and `ControlPersist`.
These support configurations such as GCP IAP tunnels without requiring a
manual config-file edit.

The **Forwarding** area accepts one `LocalForward`, `RemoteForward`, or
`DynamicForward` directive per line, including multiple directives of the same
type. Any other host-level SSH option can be entered in **Additional
directives**, one `Directive value` entry per line.

## Vault profiles

A profile is a named password, created with **Vault → Create / update profile…**. Assign
one from the host editor's dropdown or **Vault → Assign profile to selected host…**; `(none)` removes the assignment.

## Security notes

- Master password is never stored. Lost key ⇒ **Reset vault…** and re-enter secrets.
- Vault file mode `0600`; config dir `0700`.
- No recovery mechanism by design.
- Host-key prompts are handled by real `ssh` inside the terminal widget.
- Vault files are format 2; ghostcrt 0.1.0 cannot open them, and existing vaults migrate on first change.

## Limitations (v1)

- Reads the top-level `~/.ssh/config` and our own includes directory; other
  `Include` directives are not followed.
- Pattern hosts (`*`, `?`, `!`) are shown as non-connectable settings entries.
- Multi-alias vault entries are per selected alias (no cross-alias fallback).
- Linux + macOS only.

## Tests

```bash
uv run pytest
uv run ruff check src tests
```

## Design decisions

`ghostcrt` owns SSH processes, PTYs, host configuration, and the encrypted vault.
`ghostty-textual` owns terminal emulation, rendering, input encoding, and scrollback.
Mouse events stay local so remote applications cannot take over pane selection.

`--config PATH` applies to both the inventory and every SSH connection/reconnect.
It uses OpenSSH's `-F` option, which also bypasses the system-wide SSH config.
The setup check requires a leading, unconditional Include covering all group
files. Existing partial or conditional includes do not satisfy this check.

GitHub CI runs tests and builds on Linux and macOS.
