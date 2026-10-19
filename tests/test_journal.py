import tempfile
import unittest
from pathlib import Path

from zerocoding.commands import attach_journal
from zerocoding.core.agent import Agent
from zerocoding.core.journal import FileJournal, journal_for
from zerocoding.core.tools import ToolRegistry


class JournalCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve() / "project"
        self.root.mkdir()
        self.store = Path(self.directory.name).resolve() / "journal"
        self.journal = FileJournal(self.root, self.store)
        self.registry = ToolRegistry(self.root, approve=lambda action, preview: True)
        self.registry.journal = self.journal

    def write(self, name, content):
        return self.registry.execute("write_file", {"path": name, "content": content})

    def edit(self, name, old, new):
        return self.registry.execute("edit_file", {"path": name, "old_text": old, "new_text": new})


class TestJournal(JournalCase):
    def test_undo_restores_edited_new_and_rewritten_files_in_one_turn(self):
        (self.root / "a.py").write_text("one\ntwo\n")
        (self.root / "b.py").write_text("keep\n")
        self.journal.begin_turn("change things")
        self.edit("a.py", "two", "TWO")
        self.write("b.py", "rewritten\n")
        self.write("new.py", "created\n")

        plan = self.journal.plan_undo(self.journal.latest())
        self.assertEqual(plan.conflicts, [])
        self.assertEqual({a.path: a.kind for a in plan.actions}, {"a.py": "restore", "b.py": "restore", "new.py": "delete"})
        self.assertEqual(self.journal.apply(plan), 3)

        self.assertEqual((self.root / "a.py").read_text(), "one\ntwo\n")
        self.assertEqual((self.root / "b.py").read_text(), "keep\n")
        self.assertFalse((self.root / "new.py").exists())
        self.assertIsNone(self.journal.latest())

    def test_several_writes_to_one_file_in_a_turn_restore_the_original(self):
        (self.root / "a.py").write_text("v0\n")
        self.journal.begin_turn("twice")
        self.write("a.py", "v1\n")
        self.write("a.py", "v2\n")

        self.journal.apply(self.journal.plan_undo(self.journal.latest()))

        self.assertEqual((self.root / "a.py").read_text(), "v0\n")

    def test_turns_are_independent_and_undone_newest_first(self):
        (self.root / "a.py").write_text("v0\n")
        self.journal.begin_turn("first")
        self.write("a.py", "v1\n")
        self.journal.begin_turn("second")
        self.write("a.py", "v2\n")

        self.assertEqual([t.label for t in self.journal.turns()], ["second", "first"])
        older = self.journal.plan_undo(self.journal.get(1))
        self.assertEqual(older.conflicts, ["a.py"])  # the second turn changed it again
        self.journal.apply(self.journal.plan_undo(self.journal.latest()))
        self.assertEqual((self.root / "a.py").read_text(), "v1\n")
        self.journal.apply(self.journal.plan_undo(self.journal.latest()))
        self.assertEqual((self.root / "a.py").read_text(), "v0\n")

    def test_a_file_changed_by_the_user_after_the_agent_is_never_overwritten(self):
        (self.root / "a.py").write_text("v0\n")
        self.journal.begin_turn("agent")
        self.write("a.py", "agent\n")
        (self.root / "a.py").write_text("user edit\n")

        plan = self.journal.plan_undo(self.journal.latest())

        self.assertEqual(plan.conflicts, ["a.py"])
        with self.assertRaises(ValueError):
            self.journal.apply(plan)
        self.assertEqual((self.root / "a.py").read_text(), "user edit\n")

    def test_a_file_changed_between_plan_and_apply_is_not_overwritten(self):
        (self.root / "a.py").write_text("v0\n")
        self.journal.begin_turn("agent")
        self.write("a.py", "agent\n")
        plan = self.journal.plan_undo(self.journal.latest())
        (self.root / "a.py").write_text("late edit\n")

        with self.assertRaises(ValueError):
            self.journal.apply(plan)
        self.assertEqual((self.root / "a.py").read_text(), "late edit\n")

    def test_a_deleted_created_file_counts_as_a_conflict_not_a_crash(self):
        self.journal.begin_turn("agent")
        self.write("new.py", "x\n")
        (self.root / "new.py").unlink()

        self.assertEqual(self.journal.plan_undo(self.journal.latest()).conflicts, ["new.py"])

    def test_file_permissions_survive_an_undo(self):
        path = self.root / "run.sh"
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        self.journal.begin_turn("agent")
        self.write("run.sh", "#!/bin/sh\necho hi\n")

        self.journal.apply(self.journal.plan_undo(self.journal.latest()))

        self.assertEqual(path.stat().st_mode & 0o777, 0o755)

    def test_denied_writes_leave_nothing_to_undo(self):
        registry = ToolRegistry(self.root, approve=lambda action, preview: False)
        registry.journal = self.journal
        self.journal.begin_turn("denied")

        registry.execute("write_file", {"path": "x.py", "content": "x"})

        self.assertIsNone(self.journal.latest())

    def test_the_journal_survives_a_restart_and_is_private(self):
        (self.root / "a.py").write_text("v0\n")
        self.journal.begin_turn("persist me")
        self.write("a.py", "v1\n")

        reopened = FileJournal(self.root, self.store)

        self.assertEqual([t.label for t in reopened.turns()], ["persist me"])
        reopened.apply(reopened.plan_undo(reopened.latest()))
        self.assertEqual((self.root / "a.py").read_text(), "v0\n")
        self.assertEqual(self.store.stat().st_mode & 0o777, 0o700)

    def test_only_the_most_recent_turns_are_kept(self):
        for number in range(25):
            self.journal.begin_turn(f"turn {number}")
            self.write(f"f{number}.py", "x\n")

        self.assertEqual(len(self.journal.turns()), 20)
        self.assertEqual(len(list(self.store.glob("turn-*.json"))), 20)

    def test_ephemeral_sessions_keep_the_journal_in_memory_only(self):
        journal = journal_for("abc", self.root, persist=False, home=self.store)
        journal.begin_turn("t")
        journal.record("a.py", None, b"x")

        self.assertFalse((self.store / "journal").exists())
        self.assertEqual(len(journal.turns()), 1)


class FakeTui:
    def __init__(self, approve=True):
        self.approve, self.messages, self.previews = approve, [], []

    def confirm_action(self, action, preview):
        self.previews.append((action, preview))
        return self.approve

    def show_info(self, text): self.messages.append(("info", text))
    def show_success(self, text): self.messages.append(("success", text))
    def show_error(self, text): self.messages.append(("error", text))


class FakeAgent:
    def __init__(self, tools):
        self.tools = tools


class TestUndoCommand(JournalCase):
    def run_undo(self, args="", approve=True):
        tui = FakeTui(approve)
        from zerocoding.commands import handle_undo
        handle_undo(args, tui, FakeAgent(self.registry))
        return tui

    def test_undo_shows_the_diff_asks_and_restores(self):
        (self.root / "a.py").write_text("one\n")
        self.journal.begin_turn("edit a")
        self.write("a.py", "two\n")

        tui = self.run_undo()

        self.assertEqual(tui.previews[0][0], "Undo changes")
        self.assertIn("-two", tui.previews[0][1])
        self.assertIn("+one", tui.previews[0][1])
        self.assertIn("not undone", tui.previews[0][1])
        self.assertEqual((self.root / "a.py").read_text(), "one\n")
        self.assertEqual(tui.messages[-1][0], "success")

    def test_declining_the_confirmation_changes_nothing(self):
        (self.root / "a.py").write_text("one\n")
        self.journal.begin_turn("edit a")
        self.write("a.py", "two\n")

        self.run_undo(approve=False)

        self.assertEqual((self.root / "a.py").read_text(), "two\n")
        self.assertIsNotNone(self.journal.latest())

    def test_list_empty_conflict_and_bad_arguments(self):
        self.assertIn("Nothing to undo", self.run_undo().messages[-1][1])
        (self.root / "a.py").write_text("one\n")
        self.journal.begin_turn("edit a")
        self.write("a.py", "two\n")
        self.assertIn("edit a", self.run_undo("list").messages[-1][1])
        (self.root / "a.py").write_text("mine\n")
        tui = self.run_undo()
        self.assertEqual(tui.messages[-1][0], "error")
        self.assertEqual(tui.previews, [])
        self.assertEqual(self.run_undo("nonsense").messages[-1][0], "error")

    def test_undo_without_a_journal_explains_itself(self):
        self.registry.journal = None

        self.assertEqual(self.run_undo().messages[-1][0], "error")


class TestAgentIntegration(JournalCase):
    def test_each_agent_turn_is_one_undoable_unit_labelled_with_the_request(self):
        from zerocoding.providers.base import ProviderTurn, ToolCall

        class Scripted:
            def __init__(self):
                self.turns = [
                    ProviderTurn(tool_calls=[ToolCall("write_file", {"path": "a.py", "content": "new\n"}, "c1")]),
                    ProviderTurn(content="done"),
                ]

            def chat(self, messages, **kwargs):
                return self.turns.pop(0)

        (self.root / "a.py").write_text("old\n")
        agent = Agent(Scripted(), tools=self.registry)

        agent.ask("please rewrite a.py", use_tools=True)

        self.assertEqual((self.root / "a.py").read_text(), "new\n")
        self.assertEqual(self.journal.latest().label, "please rewrite a.py")
        self.journal.apply(self.journal.plan_undo(self.journal.latest()))
        self.assertEqual((self.root / "a.py").read_text(), "old\n")

    def test_attach_journal_keys_it_by_session_and_respects_persistence(self):
        class Session: id = "sess-1"
        class Manager:
            persist = False

        attach_journal(self.registry, Session(), Manager())

        self.assertIsNone(self.registry.journal.directory)
        attach_journal(None, Session(), Manager())  # no tools: nothing to attach, no crash


if __name__ == "__main__":
    unittest.main()
