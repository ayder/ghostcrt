# Changelog

## Unreleased

- Vault password profiles: store a password once under a profile id, pick it per host from the host editor dropdown or the Vault menu; vault files are now format 2, which 0.1.0 cannot open, and existing vaults migrate on first change.
- Group picker: Create/Choose now honours a highlighted group when the name box is empty, and a cancelled picker warns that the host was not saved instead of dropping it in silence.
