import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from zerocoding.core.command_policy import CommandPolicy
from zerocoding.core.tools import ToolRegistry

GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": os.environ.get("PATH", ""),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, env=GIT_ENV, capture_output=True, text=True, check=True).stdout


def init_repo(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("one\n")
    (root / "b.txt").write_text("two\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "first")


class GitCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.asked = []
        self.answer = True

    def registry(self, policy=None):
        def approve(action, preview):
            self.asked.append((action, preview))
            return self.answer
        return ToolRegistry(self.root, approve=approve, policy=policy or CommandPolicy())

    def names(self, registry):
        return {spec["function"]["name"] for spec in registry.schemas}


class TestGitAvailability(GitCase):
    def test_no_git_tools_outside_a_repository(self):
        self.assertTrue({"git", "git_commit"}.isdisjoint(self.names(self.registry())))

    def test_git_tools_appear_inside_a_repository_and_only_git_is_read_only(self):
        init_repo(self.root)
        registry = self.registry()

        self.assertTrue({"git", "git_commit"} <= self.names(registry))
        self.assertTrue(registry.is_read_only("git"))
        self.assertFalse(registry.is_read_only("git_commit"))
        self.assertIn("git", {s["function"]["name"] for s in registry.read_only_schemas})
        self.assertNotIn("git_commit", {s["function"]["name"] for s in registry.read_only_schemas})

    def test_plan_mode_allows_git_inspection_but_blocks_commit(self):
        init_repo(self.root)
        registry = self.registry()
        (self.root / "a.txt").write_text("changed\n")

        self.assertIn("a.txt", registry.execute("git", {"action": "status"}, plan_mode=True))
        blocked = registry.execute("git_commit", {"message": "x", "paths": ["a.txt"]}, plan_mode=True)
        self.assertIn("blocked in Plan mode", blocked)
        self.assertEqual(self.asked, [])

    def test_idle_schema_cost_of_the_git_tools_stays_small(self):
        from zerocoding.core.tokens import estimate_tokens
        plain = self.registry()
        init_repo(self.root)
        with_git = self.registry()
        extra = [s for s in with_git.schemas if s["function"]["name"] in {"git", "git_commit"}]

        self.assertLessEqual(estimate_tokens(extra), 200)
        self.assertEqual(len(plain.schemas) + 2, len(with_git.schemas))


class TestGitRead(GitCase):
    def setUp(self):
        super().setUp()
        init_repo(self.root)
        self.registry_ = self.registry()

    def run_git(self, **args):
        return self.registry_.execute("git", args)

    def test_status_diff_and_log(self):
        (self.root / "a.txt").write_text("one\nmore\n")
        (self.root / "new.txt").write_text("n\n")

        status = self.run_git(action="status")
        self.assertIn("## main", status)
        self.assertIn("M a.txt", status)
        self.assertIn("?? new.txt", status)
        self.assertIn("+more", self.run_git(action="diff"))
        self.assertEqual(self.run_git(action="diff", staged=True), "No changes.")
        self.assertIn("first", self.run_git(action="log", limit=5))

    def test_clean_tree_and_unknown_action(self):
        self.assertEqual(self.run_git(action="status").splitlines()[0], "## main")
        with self.assertRaisesRegex(ValueError, "Unknown git action"):
            self.run_git(action="push")

    def test_paths_are_scoped_to_the_workspace(self):
        for bad in ("../outside", "/etc/passwd", ".git/config"):
            with self.assertRaises(ValueError, msg=bad):
                self.run_git(action="diff", path=bad)

    def test_repository_config_cannot_run_code_during_reads(self):
        marker = self.root.parent / f"{self.root.name}-marker"
        self.addCleanup(lambda: marker.unlink() if marker.exists() else None)
        git(self.root, "config", "core.fsmonitor", f"touch {marker}; echo")
        git(self.root, "config", "core.pager", f"touch {marker}; cat")
        git(self.root, "config", "diff.external", f"sh -c 'touch {marker}'")
        git(self.root, "config", "diff.evil.textconv", f"sh -c 'touch {marker}; cat' --")
        (self.root / ".gitattributes").write_text("*.txt diff=evil\n")
        (self.root / "a.txt").write_text("changed\n")

        for action in ("status", "diff", "log"):
            self.run_git(action=action)
        self.run_git(action="diff", staged=True)

        self.assertFalse(marker.exists(), "git ran repository-controlled code")

    def test_a_read_does_not_modify_the_index_or_worktree(self):
        before = git(self.root, "status", "--porcelain=v2")
        self.run_git(action="status")
        self.run_git(action="diff")

        self.assertEqual(git(self.root, "status", "--porcelain=v2"), before)

    def test_long_diffs_are_truncated_with_a_hint(self):
        (self.root / "a.txt").write_text("x\n" * 20000)

        out = self.run_git(action="diff")

        self.assertIn("output truncated", out)
        self.assertLess(len(out), 9000)


class TestGitCommit(GitCase):
    def setUp(self):
        super().setUp()
        init_repo(self.root)
        # commit needs an identity; the hardened environment still reads HOME, so provide one through env.
        for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            os.environ[key] = GIT_ENV[key]
            self.addCleanup(os.environ.pop, key, None)
        self.policy = CommandPolicy(env_passthrough=CommandPolicy().env_passthrough | {
            "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_CONFIG_GLOBAL"})
        os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
        self.addCleanup(os.environ.pop, "GIT_CONFIG_GLOBAL", None)
        self.registry_ = self.registry(self.policy)

    def commit(self, **args):
        return self.registry_.execute("git_commit", args)

    def test_approved_commit_contains_only_the_listed_paths(self):
        (self.root / "a.txt").write_text("changed\n")
        (self.root / "b.txt").write_text("also changed\n")
        git(self.root, "add", "b.txt")  # already staged by the user: must stay staged, not enter the commit

        result = self.commit(message="update a", paths=["a.txt"])

        self.assertIn("Committed 1 file", result)
        self.assertEqual(git(self.root, "show", "--name-only", "--format=%s", "HEAD").split(), ["update", "a", "a.txt"])
        self.assertEqual(git(self.root, "diff", "--cached", "--name-only").split(), ["b.txt"])
        action, preview = self.asked[0]
        self.assertEqual(action, "Git commit")
        self.assertIn("update a", preview)
        self.assertIn("a.txt", preview)

    def test_denied_commit_changes_nothing(self):
        (self.root / "a.txt").write_text("changed\n")
        self.answer = False
        head = git(self.root, "rev-parse", "HEAD")

        self.assertIn("denied by user", self.commit(message="x", paths=["a.txt"]))
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.root, "diff", "--cached", "--name-only"), "")

    def test_new_untracked_files_can_be_committed(self):
        (self.root / "fresh.py").write_text("print(1)\n")

        self.assertIn("Committed", self.commit(message="add fresh", paths=["fresh.py"]))
        self.assertIn("fresh.py", git(self.root, "ls-files"))

    def test_invalid_requests_are_rejected_before_asking(self):
        (self.root / "a.txt").write_text("changed\n")
        for args in ({"message": "", "paths": ["a.txt"]}, {"message": "m", "paths": []}, {"message": "m", "paths": "a.txt"},
                     {"message": "m", "paths": ["../x"]}, {"message": "m", "paths": ["."]},
                     {"message": "m", "paths": ["b.txt"]}):  # b.txt has no changes
            with self.assertRaises(ValueError, msg=str(args)):
                self.commit(**args)
        self.assertEqual(self.asked, [])

    def test_repository_hooks_run_so_commits_are_never_auto_approved(self):
        hook = self.root / ".git" / "hooks" / "pre-commit"
        marker = self.root / "hook-ran.txt"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        hook.chmod(0o755)
        (self.root / "a.txt").write_text("changed\n")

        self.commit(message="with hook", paths=["a.txt"])

        self.assertTrue(marker.exists())
        from zerocoding.core.permissions import PermissionPolicy
        for mode in ("ask", "auto", "yolo"):
            self.assertIsNone(PermissionPolicy(self.root, mode).decide("Git commit", "preview"), mode)

    def test_a_failing_hook_reports_failure_without_claiming_success(self):
        hook = self.root / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho no >&2\nexit 1\n")
        hook.chmod(0o755)
        (self.root / "a.txt").write_text("changed\n")

        self.assertIn("git commit failed", self.commit(message="x", paths=["a.txt"]))


if __name__ == "__main__":
    unittest.main()
