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

    def test_pinned_projects_persist_and_unpin(self) -> None:
        project_a = Path(self.tempdir.name) / "project-a"
        project_b = Path(self.tempdir.name) / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        RUNNER.pin_projects([project_b, project_a])
        self.assertEqual(RUNNER.pinned_projects(), {project_a, project_b})
        RUNNER.unpin_projects([project_a])
        self.assertEqual(RUNNER.pinned_projects(), {project_b})

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
