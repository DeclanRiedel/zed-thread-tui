# Zed Thread TUI

Terminal UI for running per-project commands across Zed projects/worktrees.

```sh
nix run .
```

The TUI keeps its own project list, reads Zed's local thread/workspace state read-only, and can discover git worktrees. Zed state sync uses internal SQLite files, so it may need adjustment if Zed changes its schema.

## Row Icons

Rows start with compact status slots:

- `*`: command is running.
- `~`: nix warm-up is running.
- `.`: idle or clean exit.
- `!`: stopped, failed, or missing command.
- `@`: most recently focused/open Zed project from Zed state.
- `^`: pinned thread, sorted before unpinned rows.
- `F`: project uses `flake.nix`.
- `S`: project uses `shell.nix` or `default.nix`.
- `-`: no nix shell detected.
- `N`: nix shell is active for that row.
- `[AI:run]`: Zed Agent thread was updated very recently, treated as responding.
- `[AI:done!]`: Zed Agent thread updated since you last marked it seen.
- `[AI:seen]`: latest known Zed Agent update was acknowledged in the TUI.
- `[AI:-]`: no known Zed Agent state for that project.

Example:

```text
> 01 *@^FN project-alpha           running      npm run dev
  02 .  S  project-beta            idle         just test
```

`N` is shown when the runner knows a live command or warm-up process is running for a project with `flake.nix`, `shell.nix`, or `default.nix`. It is process-based: the runner records the process group it started and refreshes whether that process group is still alive. It does not introspect arbitrary external shells.

AI badges are best-effort. They read Zed's local thread database, map rows to projects with `folder_paths`, and store acknowledgement state in `ai-seen.json`.
Focusing a project after it shows `[AI:done!]` automatically marks that response `[AI:seen]`.

## Controls

- `up` / `down`: select thread.
- `/` / `u`: filter / clear filter.
- `o`: cycle sort mode.
- `enter` / `e`: edit command.
- `c` / `P`: cycle preset / save current command as preset.
- `t`: toggle log tail pane.
- `f`: focus/open selected project in Zed.
- `p`: add project path.
- `h`: hide selected project from the default list.
- `b`: pin/unpin selected thread.
- `A` / `U` / `M`: mark selected AI response seen / unchecked / mark all done seen.
- `s`: start or rerun selected command.
- `r`: stop all, focus selected project, run selected command.
- `x` / `a`: stop selected / stop all.
- `w` / `W`: warm selected/all nix shells.
- `q` / `Q`: quit and leave commands running / quit and stop all.
- `<leader>`: toggle leader mode and change the statusline color.
- `<leader>9f`: focus slot 9 from inside the TUI.
- `<leader>9r`: stop all and run slot 9 from inside the TUI.
- `<leader>9x`: stop slot 9 from inside the TUI.

## Commands

```sh
nix run . -- --list-zed-projects
nix run . -- --sync-zed-projects
nix run . -- --add-project /path/to/project-alpha
nix run . -- --hide-project /path/to/project-alpha
nix run . -- --unhide-project /path/to/project-alpha
nix run . -- --list-hidden
nix run . -- --pin-project /path/to/project-alpha
nix run . -- --unpin-project /path/to/project-alpha
nix run . -- --list-pinned
nix run . -- --set-preset /path/to/project-alpha dev "npm run dev"
nix run . -- --list-presets /path/to/project-alpha
nix run . -- --stop-all
nix run . -- --focus-limit 4
nix run . -- --install-zed-config
nix run . -- --list-slots
nix run . -- --reassign-slot /path/to/project-alpha 9
nix run . -- --focus-id 9
nix run . -- --stop-all-first --focus-zed-on-run --run-id 9
nix run . -- --stop-id 9
```

## Zed

Useful task names:

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
    "alt-z": ["terminal::SendText", "f"]
  }
}
```

Inside the TUI, the slot combo order is number then action, e.g. `<leader>9f`.

After `--install-zed-config --slot-count 9`, you can add generated task bindings for fast slot access from Zed itself:

```jsonc
{
  "context": "Workspace",
  "bindings": {
    "space f 9": ["task::Spawn", { "task_name": "thread runner: focus 9" }],
    "space r 9": ["task::Spawn", { "task_name": "thread runner: stop all then run 9" }],
    "space x 9": ["task::Spawn", { "task_name": "thread runner: stop 9" }]
  }
}
```

The focus action uses `zed --existing <project>`. Zed does not expose a public CLI/API to select an arbitrary existing Agent thread by ID.

The TUI statusline shows the configured leader key, defaulting to `space`, so the slot bindings read as `space f 9`, `space r 9`, and `space x 9`.

## Development

```sh
nix flake check
nix build .
nix develop
```
