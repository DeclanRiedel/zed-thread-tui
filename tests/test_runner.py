import importlib.machinery
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = importlib.machinery.SourceFileLoader("runner", str(ROOT / "bin" / "zed-thread-runner")).load_module()


class RunnerStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.configdir = tempfile.TemporaryDirectory()
        self.old_state = os.environ.get("XDG_STATE_HOME")
        self.old_config = os.environ.get("XDG_CONFIG_HOME")
        self.old_zed_state = RUNNER.ZED_STATE_DIR
        os.environ["XDG_STATE_HOME"] = self.tempdir.name
        os.environ["XDG_CONFIG_HOME"] = self.configdir.name
        RUNNER.ZED_STATE_DIR = Path(self.tempdir.name) / "zed"

    def tearDown(self) -> None:
        if self.old_state is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.old_state
        if self.old_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old_config
        RUNNER.ZED_STATE_DIR = self.old_zed_state
        self.tempdir.cleanup()
        self.configdir.cleanup()

    def test_focus_cap_keeps_projects_registered(self) -> None:
        base = Path(self.tempdir.name)
        projects = []
        for index in range(1, 6):
            project = base / f"project-{index}"
            project.mkdir()
            projects.append(project)
        RUNNER.add_projects(projects)
        for project in projects:
            popped = RUNNER.record_focused_project(project, limit=4)
        self.assertEqual([path.name for path in RUNNER.load_focus_history()], ["project-5", "project-4", "project-3", "project-2"])
        self.assertEqual([path.name for path in RUNNER.load_projects()], [f"project-{index}" for index in range(1, 6)])
        self.assertEqual([path.name for path in popped], ["project-1"])

    def test_nix_wrapper_detection(self) -> None:
        base = Path(self.tempdir.name)
        flake_project = base / "flake-project"
        shell_project = base / "shell-project"
        plain_project = base / "plain-project"
        for project in (flake_project, shell_project, plain_project):
            project.mkdir()
        (flake_project / "flake.nix").write_text("{}")
        (shell_project / "shell.nix").write_text("{}")
        self.assertEqual(RUNNER.nix_wrapper_kind(flake_project), "flake")
        self.assertEqual(RUNNER.nix_wrapper_kind(shell_project), "shell")
        self.assertEqual(RUNNER.nix_wrapper_kind(plain_project), "none")

    def test_slots_are_stable_and_reassignable(self) -> None:
        base = Path(self.tempdir.name)
        project_a = base / "project-a"
        project_b = base / "project-b"
        project_c = base / "project-c"
        for project in (project_a, project_b, project_c):
            project.mkdir()
        slots = RUNNER.ensure_slots([project_a, project_b])
        self.assertEqual(slots[str(project_a)], 1)
        self.assertEqual(slots[str(project_b)], 2)
        self.assertEqual(RUNNER.project_for_slot(2), project_b)
        RUNNER.reassign_slot(project_c, 9)
        slots = RUNNER.ensure_slots([project_a, project_b, project_c])
        self.assertEqual(slots[str(project_c)], 9)
        self.assertEqual(RUNNER.project_for_slot(9), project_c)

    def test_remote_slot_key_resolution(self) -> None:
        key = RUNNER.remote_thread_key("devbox", "/srv/project")
        RUNNER.save_slots({key: 9})

        self.assertEqual(RUNNER.key_for_slot(9), key)
        self.assertIsNone(RUNNER.project_for_slot(9))
        self.assertEqual(RUNNER.remote_parts_from_key(key), ("devbox", "/srv/project"))

    def test_leader_combo_cli_parses_and_hides_slot(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        RUNNER.save_slots({str(project): 9})

        self.assertEqual(RUNNER.parse_leader_combo("9R1"), (9, "R1"))
        self.assertIsNone(RUNNER.parse_leader_combo("R1"))
        self.assertEqual(RUNNER.run_leader_combo("9h", focus_zed=False, focus_limit=4), 0)
        self.assertEqual(RUNNER.hidden_thread_keys(), {str(project)})

    def test_leader_combo_cli_dispatches_command_slot(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        RUNNER.save_slots({str(project): 9})
        calls = []
        original_run_slot = RUNNER.run_slot
        try:
            RUNNER.run_slot = lambda *args, **kwargs: calls.append((args, kwargs)) or 0

            self.assertEqual(RUNNER.run_leader_combo("9R2", focus_zed=True, focus_limit=4), 0)
        finally:
            RUNNER.run_slot = original_run_slot

        self.assertEqual(calls, [((9, None), {"focus_zed": True, "stop_all_first": True, "focus_limit": 4, "command_slot": 2})])

    def test_command_history_deduplicates_and_limits(self) -> None:
        key = "ssh:devbox:/srv/project"
        RUNNER.record_command_history(key, "just test", limit=3)
        RUNNER.record_command_history(key, "npm run dev", limit=3)
        RUNNER.record_command_history(key, "just test", limit=3)
        RUNNER.record_command_history(key, "pytest", limit=3)
        RUNNER.record_command_history(key, "cargo test", limit=3)

        self.assertEqual(RUNNER.load_command_history()[key], ["cargo test", "pytest", "just test"])

    def test_command_completion_uses_common_prefix_or_first_match(self) -> None:
        self.assertEqual(
            RUNNER.complete_command_value("npm", ["npm run dev", "npm run test", "just test"]),
            "npm run ",
        )
        self.assertEqual(
            RUNNER.complete_command_value("just", ["npm run dev", "just test"]),
            "just test",
        )
        self.assertEqual(RUNNER.complete_command_value("cargo", ["just test"]), "cargo")

    def test_thread_aliases_apply_to_local_and_remote_threads(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        RUNNER.set_thread_alias(str(project), "api")
        self.assertEqual(RUNNER.load_aliases()[str(project)], "api")
        threads = RUNNER.build_threads([project], None)
        self.assertEqual(threads[0].name, "api")
        self.assertEqual(threads[0].base_name, "project")

        remote_key = RUNNER.remote_thread_key("devbox", "/srv/project")
        RUNNER.set_thread_alias(remote_key, "remote-api")
        self.assertEqual(RUNNER.load_aliases()[remote_key], "remote-api")
        RUNNER.unset_thread_alias(remote_key)
        self.assertNotIn(remote_key, RUNNER.load_aliases())

    def test_compact_row_uses_short_status_and_alias(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        thread = RUNNER.ThreadCommand(project=project, command="npm run dev", alias="api")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")

        row = ui.compact_row(">", "01", "* ^FN", thread, "running", "npm run dev", {"state": "done"})

        self.assertIn("api", row)
        self.assertIn("run", row)
        self.assertIn("npm:dev", row)
        self.assertIn("!", row)
        self.assertLess(len(row), 52)

    def test_row_command_uses_cmd1_and_optional_cmd2(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        RUNNER.save_thread_command_slot(str(project), 1, "nix run .#dev")
        RUNNER.save_thread_command_slot(str(project), 2, "nix run .#test")
        thread = RUNNER.ThreadCommand(project=project, command="manual")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")

        self.assertEqual(ui.row_command_text(thread), "nix run .#dev")
        ui.apply_setting(None, "multi_command_mode")
        ui.apply_setting(None, "show_cmd2_in_rows")
        self.assertEqual(ui.row_command_text(thread), "nix run .#dev  nix run .#test")
        ui.use_command_slot(2, run=False)
        self.assertEqual(ui.row_command_text(thread), "nix run .#dev  [nix run .#test]")

        empty = RUNNER.ThreadCommand(project=project / "empty", command="")
        ui = RUNNER.RunnerUi([empty], False, 4, "source")
        ui.multi_command_mode = True
        ui.show_cmd2_in_rows = True
        self.assertEqual(ui.row_command_text(empty), "<cmd>  <cmd2>")

    def test_command_slots_persist_active_and_complete(self) -> None:
        key = "ssh:devbox:/srv/project"

        state = RUNNER.save_thread_command_slot(key, 1, "nix run .#dev")
        state = RUNNER.save_thread_command_slot(key, 2, "nix run .#test")
        RUNNER.save_commands({key: "manual"})

        self.assertEqual(state["cmd1"], "nix run .#dev")
        self.assertEqual(state["cmd2"], "nix run .#test")
        self.assertEqual(state["active"], "manual")
        self.assertEqual(RUNNER.command_for_slot(key, 1), "nix run .#dev")
        self.assertEqual(RUNNER.effective_command_for_key(key, None), "nix run .#dev")
        self.assertEqual(RUNNER.active_command_slot(key, "nix run .#dev"), "1")
        self.assertEqual(RUNNER.active_command_slot(key, "nix develop"), "manual")
        self.assertEqual(RUNNER.complete_command_value("nix run .#d", [state["cmd1"], state["cmd2"]]), "nix run .#dev")

    def test_leader_two_phase_runs_command_slot(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        thread = RUNNER.ThreadCommand(project=project, command="")
        RUNNER.save_thread_command_slot(str(project), 1, "nix run .#dev")
        RUNNER.save_thread_command_slot(str(project), 2, "nix run .#test")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")
        ui.multi_command_mode = True
        ui.slots = {str(project): 9}
        calls = []

        def fake_start(stop_all_first: bool, command_slot: str = "manual") -> None:
            calls.append((ui.current.command, stop_all_first, command_slot))

        ui.start_current = fake_start

        ui.leader_active = True
        ui.handle_leader_key(None, ord("9"))
        ui.handle_leader_key(None, ord("R"))
        ui.handle_leader_key(None, ord("2"))

        self.assertEqual(calls, [("nix run .#test", True, "2")])
        self.assertFalse(ui.leader_active)
        self.assertEqual(ui.leader_pending_action, "")
        self.assertEqual(RUNNER.load_commands()[str(project)], "nix run .#test")

    def test_leader_two_phase_start_and_edit_command_slot(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        thread = RUNNER.ThreadCommand(project=project, command="")
        RUNNER.save_thread_command_slot(str(project), 1, "nix run .#dev")
        RUNNER.save_thread_command_slot(str(project), 2, "nix run .#test")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")
        ui.multi_command_mode = True
        ui.slots = {str(project): 9}
        calls = []
        edited = []

        def fake_start(stop_all_first: bool, command_slot: str = "manual") -> None:
            calls.append((ui.current.command, stop_all_first, command_slot))

        def fake_edit(stdscr, slot: int) -> None:
            edited.append(slot)

        ui.start_current = fake_start
        ui.edit_command_slot = fake_edit

        ui.leader_active = True
        ui.handle_leader_key(None, ord("9"))
        ui.handle_leader_key(None, ord("s"))
        ui.handle_leader_key(None, ord("1"))
        ui.leader_active = True
        ui.handle_leader_key(None, ord("9"))
        ui.handle_leader_key(None, ord("e"))
        ui.handle_leader_key(None, ord("2"))

        self.assertEqual(calls, [("nix run .#dev", False, "1")])
        self.assertEqual(edited, [2])

    def test_selected_row_pending_start_and_edit_require_multi_command_mode(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        thread = RUNNER.ThreadCommand(project=project, command="")
        RUNNER.save_thread_command_slot(str(project), 1, "nix run .#dev")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")
        calls = []
        edited = []

        def fake_start(stop_all_first: bool, command_slot: str = "manual") -> None:
            calls.append((ui.current.command, command_slot))

        def fake_edit(stdscr, slot: int) -> None:
            edited.append(slot)

        ui.start_current = fake_start
        ui.edit_command_slot = fake_edit
        ui.handle_key(None, ord("s"))

        self.assertEqual(calls, [("", "manual")])

        ui.multi_command_mode = True
        ui.handle_key(None, ord("s"))
        ui.handle_key(None, ord("1"))
        ui.handle_key(None, ord("e"))
        ui.handle_key(None, ord("1"))

        self.assertEqual(calls[-1], ("nix run .#dev", "1"))
        self.assertEqual(edited, [1])

    def test_process_registry_records_command_slot(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()

        class FakeProcess:
            pid = 12345

        original_getpgid = RUNNER.os.getpgid
        RUNNER.os.getpgid = lambda pid: 54321
        try:
            RUNNER.register_process(project, FakeProcess(), "nix run .#dev", "1")
        finally:
            RUNNER.os.getpgid = original_getpgid

        self.assertEqual(RUNNER.load_processes()[str(project)]["command_slot"], "1")

    def test_stop_all_registered_processes_keeps_ssh_connections(self) -> None:
        RUNNER.save_processes(
            {
                "ssh-connection:tunnel": {"pid": 1, "pgid": 111, "command": "ssh -N devbox", "command_slot": "manual"},
                "project": {"pid": 2, "pgid": 222, "command": "sleep 5", "command_slot": "manual"},
            }
        )
        stopped = []
        original_stop = RUNNER.stop_process_group
        RUNNER.stop_process_group = lambda pgid: stopped.append(pgid)
        try:
            count = RUNNER.stop_all_registered_processes()
        finally:
            RUNNER.stop_process_group = original_stop

        self.assertEqual(count, 1)
        self.assertEqual(stopped, [222])
        self.assertIn("ssh-connection:tunnel", RUNNER.load_processes())

    def test_run_slot_can_use_command_slot(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        RUNNER.save_slots({str(project): 7})
        RUNNER.save_thread_command_slot(str(project), 1, "nix run .#dev")
        calls = []
        original_run_project = RUNNER.run_project

        def fake_run_project(project_arg, command, focus_zed, stop_all_first, focus_limit, command_slot="manual"):
            calls.append((project_arg, command, focus_zed, stop_all_first, focus_limit, command_slot))
            return 0

        RUNNER.run_project = fake_run_project
        try:
            result = RUNNER.run_slot(7, None, focus_zed=True, stop_all_first=True, focus_limit=4, command_slot=1)
        finally:
            RUNNER.run_project = original_run_project

        self.assertEqual(result, 0)
        self.assertEqual(calls, [(project, "nix run .#dev", True, True, 4, "1")])
        self.assertEqual(RUNNER.load_commands()[str(project)], "nix run .#dev")

    def test_zed_focus_binding_can_include_threads_menu(self) -> None:
        focus_only = RUNNER.zed_focus_binding("thread runner: focus 9", False)
        focus_menu = RUNNER.zed_focus_binding("thread runner: focus 9", True)

        self.assertEqual(focus_only, ["task::Spawn", {"task_name": "thread runner: focus 9"}])
        self.assertEqual(focus_menu[0], "action::Sequence")
        self.assertIn("agents_sidebar::ToggleThreadSwitcher", focus_menu[1])

    def test_settings_apply_persists_toggles(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        ui = RUNNER.RunnerUi([RUNNER.ThreadCommand(project=project, command="")], False, 4, "source")

        ui.apply_setting(None, "focus_zed_on_run")
        ui.apply_setting(None, "multi_command_mode")
        ui.apply_setting(None, "show_cmd2_in_rows")
        ui.apply_setting(None, "trust_zed_focus")
        ui.apply_setting(None, "open_threads_menu_on_focus")

        config = RUNNER.load_config()
        self.assertTrue(ui.focus_zed_on_run)
        self.assertTrue(ui.multi_command_mode)
        self.assertTrue(ui.show_cmd2_in_rows)
        self.assertTrue(ui.trust_zed_focus)
        self.assertTrue(config["focus_zed_on_run"])
        self.assertTrue(config["multi_command_mode"])
        self.assertTrue(config["show_cmd2_in_rows"])
        self.assertTrue(config["trust_zed_focus"])
        self.assertTrue(config["open_threads_menu_on_focus"])

    def test_ssh_connections_persist_without_running_command(self) -> None:
        RUNNER.save_ssh_connections([{"name": "dev-tunnel", "command": "ssh -N devbox"}])

        self.assertEqual(RUNNER.load_ssh_connections(), [{"name": "dev-tunnel", "command": "ssh -N devbox"}])

    def test_ssh_connections_support_auto_start_flag(self) -> None:
        RUNNER.save_ssh_connections(
            [
                {"name": "dev-tunnel", "command": "ssh -N devbox", "auto_start": True},
                {"name": "manual", "command": "ssh devbox"},
            ]
        )

        connections = RUNNER.load_ssh_connections()
        self.assertTrue(connections[0]["auto_start"])
        self.assertNotIn("auto_start", connections[1])

    def test_auto_start_only_starts_enabled_ssh_connections(self) -> None:
        RUNNER.save_ssh_connections(
            [
                {"name": "auto", "command": "ssh -N devbox", "auto_start": True},
                {"name": "manual", "command": "ssh devbox"},
            ]
        )
        ui = RUNNER.RunnerUi([], False, 4, "source")
        started = []
        ui.is_ssh_connection_running = lambda name: False
        ui.start_ssh_connection = lambda connection, quiet=False: started.append(connection["name"]) or True

        ui.auto_start_ssh_connections()

        self.assertEqual(started, ["auto"])

    def test_thread_ssh_dependency_persists_and_starts_before_run(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        thread = RUNNER.ThreadCommand(project=project, command="just dev")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")
        RUNNER.save_ssh_connections([{"name": "dev-tunnel", "command": "ssh -N devbox"}])
        ui.thread_ssh_dependencies = RUNNER.set_thread_ssh_dependency(thread.key, "dev-tunnel")
        started = []
        ui.is_ssh_connection_running = lambda name: False
        ui.start_ssh_connection = lambda connection, quiet=False: started.append(connection["name"]) or True

        self.assertTrue(ui.ensure_thread_ssh_dependency(thread))
        self.assertEqual(started, ["dev-tunnel"])

    def test_ssh_connection_name_can_be_derived_from_pasted_command(self) -> None:
        command = "ssh -R 5052:localhost:5174 user@example.test"

        self.assertEqual(RUNNER.ssh_connection_name_from_command(command), "user@example.test")

    def test_ssh_connection_runtime_adds_no_remote_command_for_tunnels(self) -> None:
        command = "ssh -R 5052:localhost:5174 user@example.test"

        self.assertEqual(
            RUNNER.ssh_connection_runtime_argv(command),
            ["ssh", "-N", "-R", "5052:localhost:5174", "user@example.test"],
        )
        self.assertEqual(RUNNER.ssh_connection_runtime_argv("ssh -N -R 5052:localhost:5174 user@example.test")[1], "-N")

    def test_ssh_connection_running_restores_from_registry(self) -> None:
        ui = RUNNER.RunnerUi([], False, 4, "source")
        RUNNER.save_processes(
            {
                "ssh-connection:tunnel": {
                    "pid": 1,
                    "pgid": 222,
                    "command": "ssh -N devbox",
                    "command_slot": "manual",
                }
            }
        )
        original_alive = RUNNER.is_pgid_alive
        RUNNER.is_pgid_alive = lambda pgid: pgid == 222
        try:
            self.assertTrue(ui.is_ssh_connection_running("tunnel"))
        finally:
            RUNNER.is_pgid_alive = original_alive

    def test_process_dashboard_lists_registered_warm_and_rider_processes(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        thread = RUNNER.ThreadCommand(project=project, command="just dev")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")
        RUNNER.save_processes(
            {
                thread.key: {"pid": 10, "pgid": 20, "command": "just dev", "command_slot": "1"},
                "ssh-connection:tunnel": {"pid": 11, "pgid": 21, "command": "ssh -N devbox", "command_slot": "manual"},
            }
        )

        class FakeProcess:
            pid = 30

            def poll(self):
                return None

        thread.warm_process = FakeProcess()
        ui.rider_processes[thread.key] = FakeProcess()
        original_alive = RUNNER.is_pgid_alive
        RUNNER.is_pgid_alive = lambda pgid: True
        try:
            labels = [label for label, _ in ui.process_dashboard_entries()]
        finally:
            RUNNER.is_pgid_alive = original_alive

        self.assertTrue(any(label.startswith("cmd") and "just dev" in label for label in labels))
        self.assertTrue(any(label.startswith("ssh") and "tunnel" in label for label in labels))
        self.assertTrue(any(label.startswith("warm") for label in labels))
        self.assertTrue(any(label.startswith("rider") for label in labels))

    def test_leader_slot_actions_include_stop_all_and_hide(self) -> None:
        project_a = Path(self.tempdir.name) / "project-a"
        project_b = Path(self.tempdir.name) / "project-b"
        project_a.mkdir()
        project_b.mkdir()
        ui = RUNNER.RunnerUi(
            [RUNNER.ThreadCommand(project=project_a, command=""), RUNNER.ThreadCommand(project=project_b, command="")],
            False,
            4,
            "source",
        )
        ui.slots = {str(project_a): 1, str(project_b): 2}
        stopped = []

        def fake_stop_all() -> None:
            stopped.append(ui.current.key)

        ui.stop_all = fake_stop_all

        ui.leader_active = True
        ui.handle_leader_key(None, ord("2"))
        ui.handle_leader_key(None, ord("a"))

        self.assertEqual(stopped, [str(project_b)])
        self.assertFalse(ui.leader_active)
        self.assertEqual(ui.selected, 1)

        ui.leader_active = True
        ui.handle_leader_key(None, ord("1"))
        ui.handle_leader_key(None, ord("h"))

        self.assertEqual([thread.project for thread in ui.threads], [project_b])
        self.assertEqual(RUNNER.hidden_thread_keys(), {str(project_a)})

    def test_leader_capital_f_focuses_rider_and_unfocuses_previous(self) -> None:
        project_a = Path(self.tempdir.name) / "project-a"
        project_b = Path(self.tempdir.name) / "project-b"
        project_a.mkdir()
        project_b.mkdir()
        ui = RUNNER.RunnerUi(
            [RUNNER.ThreadCommand(project=project_a, command=""), RUNNER.ThreadCommand(project=project_b, command="")],
            False,
            4,
            "source",
        )
        ui.slots = {str(project_a): 1, str(project_b): 2}
        launched = []

        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
                self.stopped = False

            def poll(self):
                return 0 if self.stopped else None

        def fake_focus(project):
            process = FakeProcess(100 + len(launched))
            launched.append((project, process))
            return process, f"focused rider: {project.name}"

        original_focus = RUNNER.focus_project_in_rider
        original_getpgid = RUNNER.os.getpgid
        original_killpg = RUNNER.os.killpg
        RUNNER.focus_project_in_rider = fake_focus
        try:
            RUNNER.os.getpgid = lambda pid: pid

            def fake_killpg(pgid, signal_number):
                for _, process in launched:
                    if process.pid == pgid:
                        process.stopped = True

            RUNNER.os.killpg = fake_killpg
            ui.leader_active = True
            ui.handle_leader_key(None, ord("1"))
            ui.handle_leader_key(None, ord("F"))
            ui.leader_active = True
            ui.handle_leader_key(None, ord("2"))
            ui.handle_leader_key(None, ord("F"))
        finally:
            RUNNER.focus_project_in_rider = original_focus
            RUNNER.os.getpgid = original_getpgid
            RUNNER.os.killpg = original_killpg

        self.assertEqual([project for project, _ in launched], [project_a, project_b])
        self.assertTrue(launched[0][1].stopped)
        self.assertEqual(list(ui.rider_processes), [str(project_b)])

    def test_thread_details_include_local_metadata(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        (project / "flake.nix").write_text("{}")
        thread = RUNNER.ThreadCommand(project=project, command="just test", alias="api")
        ui = RUNNER.RunnerUi([thread], False, 4, "source")

        details = "\n".join(ui.thread_details(thread))

        self.assertIn("name: api", details)
        self.assertIn("command: just test", details)
        self.assertIn("nix: flake", details)

    def test_command_history_picker_empty_state(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        ui = RUNNER.RunnerUi([RUNNER.ThreadCommand(project=project, command="")], False, 4, "source")

        ui.pick_command_history(None)

        self.assertIn("no command history", ui.message)

    def test_pinned_projects_persist_and_unpin(self) -> None:
        project_a = Path(self.tempdir.name) / "project-a"
        project_b = Path(self.tempdir.name) / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        RUNNER.pin_projects([project_b, project_a])
        self.assertEqual(RUNNER.pinned_projects(), {project_a, project_b})
        RUNNER.unpin_projects([project_a])
        self.assertEqual(RUNNER.pinned_projects(), {project_b})

    def test_hidden_threads_support_local_and_remote_keys(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        remote_key = RUNNER.remote_thread_key("devbox", "/srv/project")

        RUNNER.hide_projects([project])
        RUNNER.hide_thread_keys([remote_key])
        self.assertIn(project, RUNNER.hidden_projects())
        self.assertEqual(RUNNER.hidden_thread_keys(), {str(project), remote_key})
        self.assertEqual(RUNNER.default_projects(project, sync_zed=False), [])

        RUNNER.unhide_thread_keys([remote_key])
        self.assertEqual(RUNNER.hidden_thread_keys(), {str(project)})
        self.assertEqual(RUNNER.hidden_thread_entries(), [str(project)])

    def test_refresh_unhidden_local_thread_adds_it_back(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        RUNNER.hide_projects([project])
        ui = RUNNER.RunnerUi([], focus_zed_on_run=False, focus_limit=4, sort_mode="source")

        RUNNER.unhide_thread_keys([str(project)])
        RUNNER.unhide_projects([project])
        ui.refresh_unhidden_thread(str(project))

        self.assertEqual(len(ui.threads), 1)
        self.assertEqual(ui.threads[0].project, project)

    def test_pinned_threads_sort_first(self) -> None:
        project_a = Path(self.tempdir.name) / "project-a"
        project_b = Path(self.tempdir.name) / "project-b"
        project_c = Path(self.tempdir.name) / "project-c"
        for project in (project_a, project_b, project_c):
            project.mkdir()
        RUNNER.pin_projects([project_c])
        ui = RUNNER.RunnerUi(
            RUNNER.build_threads([project_a, project_b, project_c], None),
            focus_zed_on_run=False,
            focus_limit=4,
            sort_mode="source",
        )

        self.assertEqual([ui.threads[index].project for index in ui.visible_indices()], [project_c, project_a, project_b])

    def test_thread_state_attr_prioritizes_failed_without_colors(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        ui = RUNNER.RunnerUi([RUNNER.ThreadCommand(project=project, command="")], False, 4, "source")
        thread = ui.threads[0]
        thread.last_status = "missing command"

        self.assertTrue(ui.thread_state_attr(thread) & RUNNER.curses.A_BOLD)

    def test_thread_state_attr_marks_running_without_colors(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        ui = RUNNER.RunnerUi([RUNNER.ThreadCommand(project=project, command="")], False, 4, "source")
        thread = ui.threads[0]

        class FakeProcess:
            def poll(self):
                return None

        thread.process = FakeProcess()
        ui.color_attr = lambda color_pair: color_pair

        self.assertEqual(ui.thread_state_attr(thread) & RUNNER.COLOR_RUNNING, RUNNER.COLOR_RUNNING)

    def test_remote_focus_uri_and_key_generation(self) -> None:
        self.assertEqual(RUNNER.remote_thread_key("devbox", "~/code/project alpha"), "ssh:devbox:~/code/project alpha")
        self.assertEqual(RUNNER.remote_ssh_uri("devbox", "~/code/project alpha"), "ssh://devbox/~/code/project%20alpha")
        self.assertEqual(RUNNER.remote_zed_uri("devbox", "/srv/project"), "zed://ssh/devbox/srv/project")

    def test_remote_focus_target_persists_and_builds_commands(self) -> None:
        RUNNER.save_remote_focus_target("devbox", "/srv/project", "cmd:zed -r {uri}")
        key = RUNNER.remote_thread_key("devbox", "/srv/project")
        self.assertEqual(RUNNER.load_remote_focus_targets()[key], "cmd:zed -r {uri}")
        self.assertEqual(RUNNER.remote_focus_command("devbox", "/srv/project"), ["zed", "-r", "ssh://devbox/srv/project"])
        self.assertEqual(
            RUNNER.remote_focus_command("devbox", "/srv/project", "zed://ssh/devbox/srv/project"),
            ["zed", "zed://ssh/devbox/srv/project"],
        )

    def test_zed_remote_specs_from_workspace_database(self) -> None:
        db_dir = RUNNER.ZED_STATE_DIR / "db" / "0-stable"
        db_dir.mkdir(parents=True)
        con = sqlite3.connect(db_dir / "db.sqlite")
        con.execute("create table remote_connections (id integer primary key, kind text, host text, port integer, user text)")
        con.execute("create table workspaces (paths text, remote_connection_id integer, timestamp text)")
        con.execute("insert into remote_connections values (?, ?, ?, ?, ?)", (1, "ssh", "devbox", 2222, "declan"))
        con.execute("insert into workspaces values (?, ?, ?)", ("/srv/project", 1, "2026-05-12 10:00:00"))
        con.commit()
        con.close()

        self.assertEqual(
            RUNNER.zed_remote_thread_specs(),
            [{"host": "declan@devbox:2222", "path": "/srv/project", "port": 2222}],
        )
        threads = RUNNER.build_remote_threads(None)
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].is_remote)
        self.assertEqual(threads[0].key, "ssh:declan@devbox:2222:/srv/project")
        RUNNER.hide_thread_keys([threads[0].key])
        self.assertEqual(RUNNER.build_remote_threads(None), [])

    def test_remote_command_uses_cached_nix_kind(self) -> None:
        command = RUNNER.remote_command_for_project("declan@devbox", "/srv/project", "just test", 2222, "flake")
        self.assertEqual(command[:4], ["ssh", "-p", "2222", "declan@devbox"])
        self.assertIn("cd /srv/project", command[-1])
        self.assertIn("nix develop", command[-1])
        self.assertNotIn("nix-shell", command[-1])

    def test_remote_nix_cache_persists(self) -> None:
        RUNNER.save_remote_nix_kind("declan@devbox", "/srv/project", "flake")
        self.assertEqual(RUNNER.cached_remote_nix_kind("declan@devbox", "/srv/project"), "flake")
        self.assertEqual(RUNNER.detect_remote_nix_kind("declan@devbox", "/srv/project", timeout=0.01), "flake")

    def test_remote_warm_command_uses_detected_wrapper(self) -> None:
        command = RUNNER.remote_warm_command_for_project("declan@devbox", "/srv/project", 2222, "shell")
        self.assertIsNotNone(command)
        self.assertEqual(command[:4], ["ssh", "-p", "2222", "declan@devbox"])
        self.assertIn("nix-shell --run true", command[-1])
        self.assertIsNone(RUNNER.remote_warm_command_for_project("declan@devbox", "/srv/project", 2222, "none"))

    def test_current_zed_project_ignores_ambiguous_workspace_timestamps(self) -> None:
        base = Path(self.tempdir.name)
        project_a = base / "project-a"
        project_b = base / "project-b"
        project_a.mkdir()
        project_b.mkdir()
        db_dir = RUNNER.ZED_STATE_DIR / "db" / "0-stable"
        db_dir.mkdir(parents=True)
        con = sqlite3.connect(db_dir / "db.sqlite")
        con.execute("create table workspaces (paths text, remote_connection_id integer, timestamp text, window_id integer)")
        con.execute("insert into workspaces values (?, ?, ?, ?)", (str(project_a), None, "2026-05-12 10:00:00", 1))
        con.execute("insert into workspaces values (?, ?, ?, ?)", (str(project_b), None, "2026-05-12 10:00:00", 1))
        con.commit()
        con.close()

        self.assertIsNone(RUNNER.current_zed_project())

    def test_current_zed_project_returns_unique_latest_workspace(self) -> None:
        base = Path(self.tempdir.name)
        project_a = base / "project-a"
        project_b = base / "project-b"
        project_a.mkdir()
        project_b.mkdir()
        db_dir = RUNNER.ZED_STATE_DIR / "db" / "0-stable"
        db_dir.mkdir(parents=True)
        con = sqlite3.connect(db_dir / "db.sqlite")
        con.execute("create table workspaces (paths text, remote_connection_id integer, timestamp text, window_id integer)")
        con.execute("insert into workspaces values (?, ?, ?, ?)", (str(project_a), None, "2026-05-12 10:00:00", 1))
        con.execute("insert into workspaces values (?, ?, ?, ?)", (str(project_b), None, "2026-05-12 10:01:00", 1))
        con.commit()
        con.close()

        self.assertEqual(RUNNER.current_zed_project(), project_b)

    def test_current_zed_remote_ignores_ambiguous_local_remote_timestamps(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        db_dir = RUNNER.ZED_STATE_DIR / "db" / "0-stable"
        db_dir.mkdir(parents=True)
        con = sqlite3.connect(db_dir / "db.sqlite")
        con.execute("create table remote_connections (id integer primary key, kind text, host text, port integer, user text)")
        con.execute("create table workspaces (paths text, remote_connection_id integer, timestamp text, window_id integer)")
        con.execute("insert into remote_connections values (?, ?, ?, ?, ?)", (1, "ssh", "devbox", None, "declan"))
        con.execute("insert into workspaces values (?, ?, ?, ?)", (str(project), None, "2026-05-12 10:00:00", 1))
        con.execute("insert into workspaces values (?, ?, ?, ?)", ("/srv/project", 1, "2026-05-12 10:00:00", 1))
        con.commit()
        con.close()

        self.assertIsNone(RUNNER.current_zed_remote_key())

    def test_tui_does_not_poll_zed_focus_by_default(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        db_dir = RUNNER.ZED_STATE_DIR / "db" / "0-stable"
        db_dir.mkdir(parents=True)
        con = sqlite3.connect(db_dir / "db.sqlite")
        con.execute("create table workspaces (paths text, remote_connection_id integer, timestamp text, window_id integer)")
        con.execute("insert into workspaces values (?, ?, ?, ?)", (str(project), None, "2026-05-12 10:00:00", 1))
        con.commit()
        con.close()
        ui = RUNNER.RunnerUi([RUNNER.ThreadCommand(project=project, command="")], False, 4, "source")

        self.assertIsNone(ui.cached_focused_project())
        ui.trust_zed_focus = True
        self.assertEqual(ui.cached_focused_project(), project)

    def test_registered_process_restores_as_running(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        process = subprocess.Popen(["sleep", "5"], preexec_fn=os.setsid)
        try:
            RUNNER.register_process(project, process, "sleep 5")
            threads = RUNNER.build_threads([project], None)
            self.assertEqual(len(threads), 1)
            self.assertEqual(threads[0].registered_pgid, os.getpgid(process.pid))
            self.assertEqual(threads[0].last_status, "running")
        finally:
            RUNNER.stop_process_group(os.getpgid(process.pid))
            process.wait(timeout=2)
            RUNNER.unregister_process(project)

    def test_ai_thread_state_done_seen_and_running(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        db_dir = RUNNER.ZED_STATE_DIR / "db" / "0-stable"
        db_dir.mkdir(parents=True)
        con = sqlite3.connect(db_dir / "db.sqlite")
        con.execute(
            """
            create table sidebar_threads (
              thread_id blob,
              session_id text,
              agent_id text,
              title text,
              updated_at text,
              folder_paths text,
              archived integer
            )
            """
        )
        con.execute(
            "insert into sidebar_threads values (?, ?, ?, ?, ?, ?, ?)",
            (b"abc", "session", "agent", "title", "2026-05-12T10:00:00+00:00", str(project), 0),
        )
        con.commit()
        con.close()

        states = RUNNER.zed_ai_thread_metadata(now=RUNNER.parse_zed_timestamp("2026-05-12T10:05:00+00:00"))
        self.assertEqual(states[str(project)]["state"], "done")
        RUNNER.save_ai_seen({str(project): "2026-05-12T10:00:00+00:00"})
        states = RUNNER.zed_ai_thread_metadata(now=RUNNER.parse_zed_timestamp("2026-05-12T10:05:00+00:00"))
        self.assertEqual(states[str(project)]["state"], "seen")
        states = RUNNER.zed_ai_thread_metadata(now=RUNNER.parse_zed_timestamp("2026-05-12T10:00:10+00:00"))
        self.assertEqual(states[str(project)]["state"], "running")

    def test_focused_done_ai_thread_is_marked_seen(self) -> None:
        project = Path(self.tempdir.name) / "project"
        project.mkdir()
        state = {
            "state": "done",
            "updated_at": "2026-05-12T10:00:00+00:00",
            "updated_ts": RUNNER.parse_zed_timestamp("2026-05-12T10:00:00+00:00"),
        }

        self.assertTrue(RUNNER.mark_ai_seen_for_project(project, state))
        self.assertEqual(RUNNER.load_ai_seen()[str(project)], "2026-05-12T10:00:00+00:00")
        self.assertEqual(state["state"], "seen")
        self.assertFalse(RUNNER.mark_ai_seen_for_project(project, state))


if __name__ == "__main__":
    unittest.main()
