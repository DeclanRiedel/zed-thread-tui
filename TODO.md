# Thread Runner Checklist

Planning convention: all plan notes and checklist notes should be saved to Obsidian. The canonical note for this project is `/home/declan/Obsidian/Notes/zed thread run script runner plan.md`.

## Core goals

- [x] Initialize this directory as a git repository.
- [x] Provide a per-thread command runner for Zed worktrees/projects.
- [x] Run project commands through `nix develop` when `flake.nix` exists.
- [x] Fall back to `nix-shell` for `shell.nix` or `default.nix`.
- [x] Provide start/rerun behavior that stops a running command before restarting it.
- [x] Provide per-thread stop.
- [x] Provide stop-all across active thread commands.
- [x] Persist the last command entered per project.
- [x] Add Zed task wiring to launch the runner from the editor.

## Follow-up goals

- [ ] Investigate whether a future Zed extension API can place controls directly in workspace UI chrome.
- [ ] Add a graphical one-line overlay mode if Zed exposes a reliable external-window workflow.
- [ ] Add log tailing per thread inside the UI.
- [ ] Add configurable default commands per project.
- [ ] Add tests around process lifecycle and nix command selection.
