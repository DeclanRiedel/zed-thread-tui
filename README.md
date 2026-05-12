# Zed Thread Run Script Runner

A small terminal UI for quickly starting, stopping, and rerunning per-project commands from Zed worktrees.

Zed currently exposes tasks and terminals as the practical integration point for this workflow. This project therefore launches a thin terminal UI from a Zed task instead of injecting controls directly into Zed's header chrome.

## Quick Start

Run through Nix:

```sh
nix run .
```

Build the runnable package:

```sh
nix build .
./result/bin/zed-thread-runner
```

Open a dev shell:

```sh
nix develop
```

Run against the current directory:

```sh
./bin/zed-thread-runner
```

Run against explicit projects/worktrees:

```sh
nix run . -- /path/to/project-a /path/to/project-b
```

If the current directory is a git repository with linked worktrees, the runner auto-discovers those worktrees when no paths are passed.

## Project Registry

The runner reads Zed's local SQLite state read-only and merges discovered Agent thread/workspace paths with its own persistent project registry and git worktree discovery.

This uses Zed internal storage, not a documented public API, so it may need adjustment if Zed changes its database schema. If that happens, the registry commands below remain the stable fallback.

List projects found from Zed's local thread/workspace state:

```sh
nix run . -- --list-zed-projects
```

Persist those Zed projects into the runner registry:

```sh
nix run . -- --sync-zed-projects
```

Disable automatic Zed-state merging for one run:

```sh
nix run . -- --no-zed-sync
```

Add projects to the runner:

```sh
nix run . -- --add-project /path/to/project-a --add-project /path/to/project-b
```

List registered projects:

```sh
nix run . -- --list-projects
```

Remove a project:

```sh
nix run . -- --remove-project /path/to/project-a
```

Open the TUI with explicit projects and register them:

```sh
nix run . -- --register-args /path/to/project-a /path/to/project-b
```

Inside the TUI, press `p` to add another project path as a runner thread.

## Controls

- `up` / `down`: select a thread.
- `enter` or `e`: edit the selected thread command.
- `p`: add a project path to the persistent runner thread list.
- `s`: start, or stop and rerun, the selected thread command.
- `r`: stop all tracked thread commands, focus/open the selected project in Zed when enabled, then run the selected thread command.
- `x`: stop the selected thread command.
- `a`: stop all running thread commands.
- `z`: focus/open the selected project in the existing Zed window.
- `w`: warm the selected project's nix shell.
- `W`: warm all detected nix shells.
- `l`: show the selected thread's log path.
- `q`: quit after stopping all running commands.

Commands are persisted per project in `$XDG_STATE_HOME/zed-thread-runner/commands.json`, or `~/.local/state/zed-thread-runner/commands.json` when `XDG_STATE_HOME` is unset.

## Nix Behavior

The runner chooses the command wrapper per project:

- `flake.nix`: `nix develop --command bash -lc '<command>'`
- `shell.nix` or `default.nix`: `nix-shell --run '<command>'`
- no nix files: `bash -lc '<command>'`

The `w` and `W` controls run a lightweight warm-up command so the project dev shell is evaluated and cached before you run the real command.

## Non-Interactive Commands

Run the saved command for a project without opening the TUI:

```sh
nix run . -- --run-project /path/to/project
```

Stop every tracked command, focus/open that project in the existing Zed window, then run its saved command:

```sh
nix run . -- --stop-all-first --focus-zed-on-run --run-project /path/to/project
```

Stop all tracked commands:

```sh
nix run . -- --stop-all
```

The focus behavior shells out to `zed --existing <project>`. That can open or focus the project/worktree in Zed, but Zed does not currently expose a CLI/API to select an arbitrary existing agent thread by ID or show a custom native indicator on that thread.

## Zed Task

This repository includes `.zed/tasks.json` with tasks for launching the runner through `nix run` against the current Zed worktree. In Zed, run `task: spawn`, then choose:

```text
thread runner: current worktree
```

For global use across projects, add the same task to `~/.config/zed/tasks.json` and update the script path if this repository moves.

From Zed's task picker, use `thread runner: register current worktree` to add the current Zed worktree/project to the runner's persistent list.

Useful keybindings in `~/.config/zed/keymap.json`:

```jsonc
{
  "context": "Workspace",
  "bindings": {
    "alt-2": ["action::Sequence", ["agent::ToggleFocus", "agents_sidebar::ToggleThreadSwitcher"]],
    "alt-r": ["task::Spawn", { "task_name": "thread runner: stop all then run current worktree" }]
  }
}
```
