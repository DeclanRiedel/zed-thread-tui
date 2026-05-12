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
