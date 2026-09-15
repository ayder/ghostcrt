# Repository instructions

@/Users/sinanalyuruk/.codex/RTK.md

## GitHub account

- Use the **ayder** GitHub account for this repository (`ayder/ghostcrt`), including pushes and pull requests. Do not use **dbsmedya**.
- Verify the active CLI account with `rtk proxy gh api user --jq .login` before GitHub writes.
- If Git selects another account from the macOS keychain, use the authenticated GitHub CLI credential helper for that command:

  ```sh
  rtk proxy git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push
  ```
