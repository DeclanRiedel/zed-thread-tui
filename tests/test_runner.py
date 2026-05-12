import importlib.machinery
import os
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
        os.environ["XDG_STATE_HOME"] = self.tempdir.name
        os.environ["XDG_CONFIG_HOME"] = self.configdir.name

    def tearDown(self) -> None:
        if self.old_state is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.old_state
        if self.old_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old_config
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


if __name__ == "__main__":
    unittest.main()
