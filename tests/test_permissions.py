import tempfile
import unittest
from pathlib import Path

from zerocoding.core.command_packs import DEFAULT_PACKS, evaluate
from zerocoding.core.permissions import PermissionPolicy


class TestCommandPacks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def allowed(self, command, packs=DEFAULT_PACKS):
        return evaluate(command, self.root, packs).allowed

    def test_safe_commands_inside_the_workspace_are_allowed(self):
        for command in ("mkdir -p calculadora/ops calculadora/config", "mkdir a", "touch a.py", "ls", "ls -la src", "pwd",
                        "cat a.py", "head -n 20 a.py", "head -5 a.py", "wc -l a.py b.py", "grep -rn foo .", "rg foo src",
                        "find . -name '*.py'", "git status", "git log --oneline -5", "git diff", "git branch", "git rev-parse HEAD"):
            self.assertTrue(self.allowed(command), command)

    def test_paths_outside_the_workspace_are_refused(self):
        for command in ("mkdir ../x", "mkdir /etc/x", "touch ~/a", "ls /", "cat ~/.ssh/id_rsa", "cat ../secret",
                        "grep -rn foo /etc", "find / -name x", "head -n 3 /etc/passwd"):
            self.assertFalse(self.allowed(command), command)

    def test_destructive_or_code_running_commands_are_not_in_the_default_packs(self):
        for command in ("rm -rf x", "rm a", "mv a b", "cp a b", "chmod +x a", "pip install x", "curl http://x", "sed -i s/a/b/ f",
                        "python main.py", "python -m pytest", "pytest", "sudo ls", "echo hi", "git push", "git commit -m x",
                        "git checkout .", "git reset --hard", "git clean -fd"):
            self.assertFalse(self.allowed(command), command)

    def test_dangerous_flags_and_git_options_are_refused(self):
        for command in ("find . -name x -delete", "find . -exec rm {} ;", "git -c core.pager=x log", "git -C / status",
                        "git diff --output=/tmp/x", "git diff --ext-diff", "rg --pre ./x foo", "git branch -D x", "git remote add o x"):
            self.assertFalse(self.allowed(command), command)

    def test_shell_syntax_is_never_auto_approved(self):
        for command in ("mkdir a && ls", "ls | wc -l", "ls; rm a", "cat a > b", "echo $(ls)", "ls `pwd`", "mkdir a\nrm b", "/bin/ls"):
            self.assertFalse(self.allowed(command), command)

    def test_symlinks_cannot_escape_the_workspace(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.root / "link").symlink_to(outside.name)
        self.assertFalse(self.allowed("cat link/secret.txt"))
        self.assertFalse(self.allowed("mkdir link/new"))

    def test_tests_pack_is_opt_in(self):
        self.assertFalse(self.allowed("python -m pytest tests/"))
        self.assertTrue(self.allowed("python -m pytest tests/", ("fs", "tests")))
        self.assertTrue(self.allowed("python3 -m unittest discover -s tests", ("tests",)))
        self.assertFalse(self.allowed("python -m pytest /etc/x.py", ("tests",)))

    def test_disabled_pack_means_its_commands_ask(self):
        self.assertFalse(self.allowed("git status", ("fs", "read")))


class TestPermissionPolicy(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def policy(self, mode):
        return PermissionPolicy(self.directory.name, mode)

    def test_ask_never_approves(self):
        policy = self.policy("ask")
        self.assertIsNone(policy.decide("Run command", "mkdir a"))
        self.assertIsNone(policy.decide("Write file", "--- /dev/null\n+++ b/a\n+x\n"))

    def test_auto_approves_only_pack_commands(self):
        policy = self.policy("auto")
        self.assertEqual(policy.decide("Run command", "mkdir a").note, "auto · fs pack")
        self.assertIsNone(policy.decide("Run command", "rm -rf a"))
        self.assertIsNone(policy.decide("Write file", "--- /dev/null\n+++ b/a\n+x\n"))
        self.assertIsNone(policy.decide("Edit file", "--- a\n+++ a\n-x\n+y\n"))
        self.assertIsNone(policy.decide("Run external tool", "anything"))

    def test_yolo_approves_everything_the_executor_asks_about(self):
        policy = self.policy("yolo")
        for action in ("Run command", "Write file", "Edit file", "Run external tool"):
            self.assertEqual(policy.decide(action, "x").note, "yolo")

    def test_unknown_modes_fall_back_to_ask_and_set_mode_validates(self):
        self.assertEqual(self.policy("bogus").mode, "ask")
        with self.assertRaises(ValueError):
            self.policy("ask").set_mode("bogus")


if __name__ == "__main__":
    unittest.main()


class TestYoloStaysInsideTheWorkspace(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.policy = PermissionPolicy(self.root, "yolo")

    def test_commands_inside_the_project_are_approved(self):
        for command in ("rm a.py", "python main.py", "git commit -m 'fix: ../x is fine in a message'",
                        "mkdir -p a/b", "sed -i s/a/b/ src/f.py", "npm test"):
            self.assertIsNotNone(self.policy.decide("Run command", command), command)

    def test_commands_that_may_leave_the_project_are_asked(self):
        for command in ("cat /etc/passwd", "ls ../..", "cat ~/.ssh/id_rsa", "rm ../x", "cp a /tmp/a", "ls $HOME",
                        "git diff --output=/tmp/x", "/usr/bin/env python x", "echo 'unterminated"):
            self.assertIsNone(self.policy.decide("Run command", command), command)

    def test_a_symlink_that_points_outside_is_asked(self):
        (self.root / "link").symlink_to("/etc")

        self.assertIsNone(self.policy.decide("Run command", "cat link/passwd"))

    def test_writes_and_edits_stay_approved(self):
        self.assertIsNotNone(self.policy.decide("Write file", "diff"))
        self.assertIsNotNone(self.policy.decide("Edit file", "diff"))


class TestYoloStillAsksForRiskyCommands(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.policy = PermissionPolicy(self.directory.name, "yolo")

    def test_network_installs_and_history_rewrites_are_asked(self):
        for command in ("git push origin main", "git push --force", "git pull", "git fetch", "git clone https://x/y",
                        "git remote add o x", "git reset --hard HEAD~1", "git clean -fd", "git rebase main",
                        "git -c user.name=x push", "curl https://example.com", "wget http://x", "ssh host", "gh pr create",
                        "pip install requests", "pip3 install x", "python -m pip install x", "python3 -m venv .v",
                        "npm install", "uv pip install x", "uv add x", "cargo add x", "apt install x"):
            self.assertIsNone(self.policy.decide("Run command", command), command)

    def test_routine_project_commands_are_still_approved(self):
        for command in ("git status", "git add a.py", "git commit -m x", "git checkout -b topic", "git diff", "git stash",
                        "python -m pytest", "python main.py", "rm a.py", "mkdir -p x/y", "npm test", "ls -la"):
            self.assertIsNotNone(self.policy.decide("Run command", command), command)

    def test_commits_are_asked_in_every_mode(self):
        for mode in ("ask", "auto", "yolo"):
            self.assertIsNone(PermissionPolicy(self.directory.name, mode).decide("Git commit", "preview"), mode)
