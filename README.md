# Zed Thread TUI

Terminal UI for starting, stopping, rerunning, and focusing commands across Zed projects/worktrees.

```sh
nix run .
```

The TUI merges projects from:

- Zed's local thread/workspace state, read-only.
- The runner's saved project registry.
- Git worktrees from the current repo.

Zed state sync uses internal SQLite files, not a public API, so it may need updates if Zed changes its schema.

The runner keeps all projects in the TUI, but caps its recent Zed focus set at 4 to avoid repeatedly opening/focusing too many heavy worktrees.

## Icons

Rows start with status icons before the project name:

- `*`: command running.
- `~`: nix warm-up running.
- `.`: idle or clean exit.
- `!`: stopped, failed, or missing command.
- `@`: most recently focused/open Zed project, based on Zed state.

Example:

```text
> *@ RevoSink                  running       npm run dev
  .  MGN-WMS                   idle          dotnet watch
```

## Controls

- `up` / `down`: select thread.
- `enter` / `e`: edit command.
- `f`: focus/open selected project in Zed.
- `p`: add a project path.
- `s`: start or rerun selected command.
- `r`: stop all, focus selected project, run selected command.
- `x`: stop selected command.
- `a`: stop all commands.
- `w` / `W`: warm selected/all nix shells.
- `l`: show selected log path.
- `q`: quit and stop commands.

## Commands

```sh
nix run . -- --list-zed-projects
nix run . -- --sync-zed-projects
nix run . -- --add-project /path/to/project
nix run . -- --remove-project /path/to/project
nix run . -- --list-projects
nix run . -- --stop-all
nix run . -- --stop-all-first --focus-zed-on-run --run-project /path/to/project
nix run . -- --focus-limit 4
```

Build and check:

```sh
nix build .
nix flake check
nix develop
```

## Zed

Tasks are in `.zed/tasks.json`. Useful task names:

- `thread runner: current worktree`
- `thread runner: all git worktrees`
- `thread runner: stop all then run current worktree`
- `thread runner: register current worktree`
- `thread runner: sync zed projects`

Useful keybindings:

```jsonc
{
  "context": "Workspace",
  "bindings": {
    "alt-2": ["action::Sequence", ["agent::ToggleFocus", "agents_sidebar::ToggleThreadSwitcher"]],
    "alt-r": ["task::Spawn", { "task_name": "thread runner: stop all then run current worktree" }]
  }
},
{
  "context": "Terminal",
  "bindings": {
    "alt-r": ["terminal::SendText", "r"],
    "alt-z": ["terminal::SendText", "z"]
  }
}
```

The focus action uses `zed --existing <project>`. Zed does not currently expose a public CLI/API to select an arbitrary existing Agent thread by ID.
