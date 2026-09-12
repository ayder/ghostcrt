# Changelog

## 0.2.1 — 2026-09-13

- Batch terminal frame refreshes to prevent pauses during fast scrollback and output bursts.
- Add a draggable history scrollbar to each SSH terminal pane.
- Add close buttons to session tabs; confirm closing running or connecting sessions through the tab, Ctrl+W, or Session menu, and confirm Ctrl+Q when sessions are live.
- Support multiline paste without bracketed paste mode, normalize Windows line endings, and report rejected pastes instead of silently dropping them.
- Report the installed package version correctly and clear the group picker hint once typing starts (fixes merged after the 0.2.0 release).

## 0.2.0 — 2026-09-11

- Vault password profiles: store a password once under a profile id, pick it per host from the host editor dropdown or the Vault menu; vault files are now format 2, which 0.1.0 cannot open, and existing vaults migrate on first change.
- Group picker: Create/Choose now honours a highlighted group when the name box is empty, and a cancelled picker warns that the host was not saved instead of dropping it in silence.
