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

## Controls

- `up` / `down`: select a thread.
- `enter` or `e`: edit the selected thread command.
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
