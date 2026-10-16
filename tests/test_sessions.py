import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from zerocoding.core.sessions import Session, SessionManager


class TestSessionManager(unittest.TestCase):
    def test_create_list_and_resume_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            session = manager.create("ollama_local", "deepseek-coder-v2", "code", "/project")
            session.skills = ["spring"]
            session.history = [{"role": "user", "content": "oi"}]
            manager.save(session)

            recent = manager.list_recent()
            loaded = manager.load(session.id)

            self.assertEqual(len(session.id), 32)
            self.assertEqual(recent[0].id, session.id)
            self.assertEqual(loaded.provider, "ollama_local")
            self.assertEqual(loaded.skills, ["spring"])
            self.assertEqual(loaded.history[0]["content"], "oi")

    def test_legacy_eight_digit_session_id_remains_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            legacy = Session(id="deadbeef", provider="local", model="old-model")
            manager.save(legacy)

            loaded = manager.load("deadbeef")

            self.assertEqual(loaded.id, "deadbeef")
            self.assertEqual(loaded.model, "old-model")

    def test_unique_uuid_prefix_resumes_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            session = Session(id="abcdef0123456789abcdef0123456789", provider="local", model="model")
            manager.save(session)

            loaded = manager.load("ABCDEF012345")

            self.assertEqual(loaded.id, session.id)

    def test_unversioned_session_loads_without_rewriting_legacy_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "deadbeef.json"
            payload = '{"id":"deadbeef","provider":"local","model":"old-model"}'
            legacy_path.write_text(payload, encoding="utf-8")
            manager = SessionManager(root)

            loaded = manager.load("deadbeef")

            self.assertEqual(loaded.model, "old-model")
            self.assertEqual(legacy_path.read_text(encoding="utf-8"), payload)

    def test_future_session_schema_is_rejected_without_changing_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_path = root / "deadbeef.json"
            payload = json.dumps({"schema_version": 999, "id": "deadbeef"})
            session_path.write_text(payload, encoding="utf-8")
            manager = SessionManager(root)

            with self.assertRaisesRegex(ValueError, "newer than supported"):
                manager.load("deadbeef")

            self.assertEqual(session_path.read_text(encoding="utf-8"), payload)

    def test_nested_non_object_history_is_rejected_as_invalid_session_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "deadbeef.json"
            session_path.write_text(
                '{"id":"deadbeef","history":' + ("[" * 1500) + "0" + ("]" * 1500) + "}",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "history"):
                SessionManager(tmp).load("deadbeef")

    def test_malformed_session_fields_are_rejected_with_field_specific_errors(self):
        invalid_fields = [
            ("skills", "python", "skills"),
            ("history", [{"role": "user", "content": None}], "history"),
            ("context_files", [{"path": "README.md", "content": 7}], "context_files"),
            ("plan_mode", "false", "plan_mode"),
            ("updated_at", "yesterday", "updated_at"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            for index, (field_name, invalid_value, expected_message) in enumerate(invalid_fields):
                session_id = f"a{index:07x}"
                payload = {"id": session_id, "schema_version": 1, field_name: invalid_value}
                (Path(tmp) / f"{session_id}.json").write_text(json.dumps(payload), encoding="utf-8")

                with self.subTest(field=field_name):
                    with self.assertRaisesRegex(ValueError, expected_message):
                        manager.load(session_id)

    def test_legacy_session_missing_optional_fields_uses_compatible_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_path = root / "deadbeef.json"
            session_path.write_text(
                '{"id":"deadbeef","provider":"local","model":"old-model"}',
                encoding="utf-8",
            )
            legacy_timestamp = 1_700_000_000.0
            os.utime(session_path, (legacy_timestamp, legacy_timestamp))

            loaded = SessionManager(root).load("deadbeef")

            self.assertEqual(loaded.skills, [])
            self.assertEqual(loaded.history, [])
            self.assertEqual(loaded.context_files, [])
            self.assertFalse(loaded.plan_mode)
            self.assertFalse(loaded.ultrathink)
            self.assertEqual(loaded.effort, "medium")
            self.assertEqual(loaded.created_at, legacy_timestamp)
            self.assertEqual(loaded.updated_at, legacy_timestamp)

    def test_ambiguous_prefix_is_rejected_and_exact_legacy_id_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            old = Session(id="deadbeef", provider="local", model="legacy")
            first = Session(id="deadbeef" + "0" * 24, provider="local", model="first")
            second = Session(id="deadbeef" + "1" * 24, provider="local", model="second")
            manager.save(old)
            manager.save(first)
            manager.save(second)

            self.assertEqual(manager.load("deadbeef").model, "legacy")
            (Path(tmp) / "deadbeef.json").unlink()
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                manager.load("deadbeef")

    def test_session_id_input_cannot_escape_the_session_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(Path(tmp) / "sessions")
            with self.assertRaisesRegex(ValueError, "hexadecimal"):
                manager.load("../outside")
            with self.assertRaisesRegex(ValueError, "hexadecimal"):
                manager.load("deadbeef*")

    def test_file_name_and_json_session_id_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            session = Session(id="deadbeef", provider="local", model="model")
            manager.save(session)
            session_path = Path(tmp) / "deadbeef.json"
            session_path.write_text('{"id":"cafebabe","provider":"local"}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not match"):
                manager.load("deadbeef")

    def test_failed_atomic_replacement_preserves_the_last_valid_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            session = manager.create("local", "model")
            path = Path(tmp) / f"{session.id}.json"
            original = path.read_bytes()
            session.history = [{"role": "user", "content": "new state"}]

            with patch("zerocoding.core.sessions.os.replace", side_effect=OSError("disk error")):
                with self.assertRaisesRegex(OSError, "disk error"):
                    manager.save(session)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [path.name])
            self.assertEqual(manager.load(session.id).history, [])

    def test_invalid_session_state_is_rejected_before_replacing_saved_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            session = manager.create("local", "model")
            path = Path(tmp) / f"{session.id}.json"
            original = path.read_bytes()
            original_updated_at = session.updated_at
            session.history = [{"role": "user", "content": None}]

            with self.assertRaisesRegex(ValueError, "history"):
                manager.save(session)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(session.updated_at, original_updated_at)
            self.assertEqual(manager.load(session.id).history, [])

    def test_ephemeral_manager_creates_in_memory_sessions_without_touching_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            manager = SessionManager(root, persist=False)

            session = manager.create("local", "model")
            manager.save(session)

            self.assertFalse(root.exists())
            self.assertEqual(manager.list_recent(), [])
            with self.assertRaisesRegex(ValueError, "disabled"):
                manager.load(session.id)

    def test_delete_many_validates_every_target_before_removing_any(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            first = manager.create("local", "first")
            second = manager.create("local", "second")

            with self.assertRaises(FileNotFoundError):
                manager.delete_many([first.id, "deadbeef"])

            self.assertEqual(manager.load(first.id).model, "first")
            self.assertEqual(manager.load(second.id).model, "second")

    def test_delete_many_rejects_non_string_ids_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)

            with self.assertRaisesRegex(ValueError, "Session ID"):
                manager.delete_many([{}])

    def test_session_listing_reports_invalid_files_without_returning_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            invalid_path = Path(tmp) / "deadbeef.json"
            invalid_path.write_text('{"secret":"conversation text",', encoding="utf-8")

            sessions, errors = manager.list_recent_with_errors(limit=None)

            self.assertEqual(sessions, [])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0][0], "deadbeef")
            self.assertNotIn("conversation text", errors[0][1])

    def test_save_removes_only_old_regular_atomic_write_temporary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = SessionManager(root)
            stale = root / ".deadbeef-abandoned.tmp"
            fresh = root / ".deadbeef-active.tmp"
            unrelated = root / ".notes-abandoned.tmp"
            outside = root / "outside.tmp"
            linked = root / ".cafebabe-linked.tmp"
            stale.write_text("stale", encoding="utf-8")
            fresh.write_text("fresh", encoding="utf-8")
            unrelated.write_text("keep", encoding="utf-8")
            outside.write_text("outside", encoding="utf-8")
            linked.symlink_to(outside)
            old = time.time() - (48 * 60 * 60)
            os.utime(stale, (old, old))
            os.utime(unrelated, (old, old))

            manager.create("local", "model")

            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(linked.is_symlink())
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside")

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions are not available")
    def test_session_directory_and_files_are_private_even_under_umask_022(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            root.mkdir(mode=0o755)
            os.chmod(root, 0o755)
            manager = SessionManager(root)
            session = manager.create("local", "model")
            path = root / f"{session.id}.json"

            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            os.chmod(path, 0o644)
            manager.load(session.id)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX symbolic links are not available")
    def test_session_manager_refuses_symlink_root_and_session_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "real-sessions"
            root.mkdir()
            linked_root = Path(tmp) / "linked-sessions"
            linked_root.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                SessionManager(linked_root).create("local", "model")

            manager = SessionManager(root)
            session = manager.create("local", "model")
            path = root / f"{session.id}.json"
            external = Path(tmp) / "outside.json"
            external.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            path.unlink()
            path.symlink_to(external)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                manager.load(session.id)
            self.assertEqual(manager.list_recent(), [])


if __name__ == "__main__":
    unittest.main()
