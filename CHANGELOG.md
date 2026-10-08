# Changelog

## 0.4.0 — 2026-10-08

- Add snippets: up to five named texts stored encrypted in the vault and edited from Vault → Snippets…. In the terminal, Ctrl+N then 1–5 types a snippet as keystrokes (`\n` is Enter, `\\` a backslash), and the footer shows a button per snippet while the terminal is focused. Outside the terminal, Ctrl+N still focuses the host list.
- Vault files are now format 3. Format 1 and 2 vaults open normally and are rewritten as format 3 on their first change; ghostcrt 0.3.2 and earlier cannot open a format 3 vault, so back up `vault.enc` first if you may need to go back.
- Ctrl+T now toggles the host list: from the terminal it shows and focuses Hosts, and from Hosts it hides them so the terminal takes the full width. Esc returns to the terminal with the host list kept beside it.

## 0.3.2 — 2026-10-05

- Preserve negotiated pixel mouse reporting when Ctrl+O recaptures the mouse, so host-group and terminal clicks retain their correct targets in Ghostty.
- Fix focus-time crashes when clicking hosts, buttons, or menu options under themes such as Nord and Catppuccin. Respect the theme's cursor text style, including `none`.
- Upgrade ghostty-textual to v0.0.5 with its exact pyghostty 0.1.3 dependency for the updated native terminal ABI. Retain GhostCRT's rendering, scrollback, input, and frame batching behavior.
- The native library now retains a base codepoint plus at most 64 additional grapheme codepoints per cell; further combining codepoints are ignored.

## 0.3.1 — 2026-09-27

- Upgrade ghostty-textual to v0.0.4 for faster styled output, selection, and hyperlink rendering. Preserve GhostCRT's 60 Hz output and scroll batching with the library's deferred rendering.

## 0.3.0 — 2026-09-25

- Introduce a compact terminal layout with a separated menu bar, one-row controls and session tabs, contextual footer hints, and a host drawer on narrow terminals. Colors follow the selected Textual theme.
- Add keyboard-navigable dropdown menus, synchronized menu highlights, disabled action styling, and consistent selection markers. Preserve host selection while filtering.
- Organize host editing into connection, authentication, and collapsible advanced settings; improve vault and filter spacing.
- Add Clone selected with copied settings and vault profile, and confirm host deletion from both the menu and editor.
- Change the terminal-release shortcut from Ctrl+] to Ctrl+T and show Ctrl+H Help in the footer.

## 0.2.2 — 2026-09-15

- Show first-connection SSH host-key confirmation in the session tab before starting saved-password login, so unknown hosts no longer disconnect immediately.
- Add real SSH integration coverage for host-key acceptance, rejection, cancellation, changed keys, and reconnecting.

## 0.2.1 — 2026-09-13

- Batch terminal frame refreshes to prevent pauses during fast scrollback and output bursts.
- Add a draggable history scrollbar to each SSH terminal pane.
- Add close buttons to session tabs; confirm closing running or connecting sessions through the tab, Ctrl+W, or Session menu, and confirm Ctrl+Q when sessions are live.
- Support multiline paste without bracketed paste mode, normalize Windows line endings, and report rejected pastes instead of silently dropping them.
- Report the installed package version correctly and clear the group picker hint once typing starts (fixes merged after the 0.2.0 release).

## 0.2.0 — 2026-09-11

- Vault password profiles: store a password once under a profile id, pick it per host from the host editor dropdown or the Vault menu; vault files are now format 2, which 0.1.0 cannot open, and existing vaults migrate on first change.
- Group picker: Create/Choose now honours a highlighted group when the name box is empty, and a cancelled picker warns that the host was not saved instead of dropping it in silence.
