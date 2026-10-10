import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from zerocoding.projects import build_scaffold, create_project, resolve_project_target


class TestProjects(unittest.TestCase):
    def test_cli_scaffold_has_entry_point_and_tests(self):
        files = build_scaffold("cli", "hello-world")

        self.assertIn("pyproject.toml", files)
        self.assertIn("src/hello_world/cli.py", files)
        self.assertIn("tests/test_cli.py", files)
        self.assertIn("[project.scripts]", files["pyproject.toml"])
        self.assertIn("argparse", files["src/hello_world/cli.py"])

    def test_api_scaffold_has_fastapi_and_test_dependencies(self):
        files = build_scaffold("api", "hello-api")

        self.assertIn("src/hello_api/main.py", files)
        self.assertIn("tests/test_api.py", files)
        self.assertIn('fastapi[standard]', files["pyproject.toml"])
        self.assertIn('"httpx"', files["pyproject.toml"])
        self.assertIn("TestClient", files["tests/test_api.py"])

    def test_javascript_cli_scaffold_uses_node_builtins(self):
        files = build_scaffold("cli", "hello-world", "javascript")

        self.assertIn('"node": ">=24"', files["package.json"])
        self.assertIn("node --test", files["package.json"])
        self.assertIn("node:util", files["src/index.js"])
        self.assertIn("node:test", files["tests/index.test.js"])
        self.assertIn("../src/index.js", files["tests/index.test.js"])

    def test_node_api_scaffolds_declare_fastify_and_inject_tests(self):
        for language, extension in (("javascript", "js"), ("typescript", "ts")):
            with self.subTest(language=language):
                files = build_scaffold("api", "hello-api", language)
                self.assertIn('"fastify": "^5.2.0"', files["package.json"])
                self.assertIn(f"src/app.{extension}", files)
                self.assertIn("app.inject", files["tests/app.test.js"])
                self.assertIn("../" + ("src" if language == "javascript" else "dist") + "/app.js", files["tests/app.test.js"])

    def test_typescript_scaffolds_build_before_running_node_tests(self):
        files = build_scaffold("cli", "hello-world", "typescript")

        self.assertIn('"build": "tsc -p tsconfig.json"', files["package.json"])
        self.assertIn('"test": "npm run build && node --test"', files["package.json"])
        self.assertIn("rootDir", files["tsconfig.json"])

    def test_unsupported_language_is_rejected(self):
        with self.assertRaises(ValueError):
            build_scaffold("cli", "sample", "go")

    def test_target_must_be_under_working_directory_and_not_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve_project_target("new-app", cwd=root), root / "new-app")
            with self.assertRaises(ValueError):
                resolve_project_target("../outside", cwd=root)
            with self.assertRaises(ValueError):
                resolve_project_target(".", cwd=root)

    def test_nonempty_directory_and_symlink_target_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing"
            existing.mkdir()
            (existing / "keep.txt").write_text("keep")
            with self.assertRaises(ValueError):
                resolve_project_target("existing", cwd=root)

            outside = root / "outside"
            outside.mkdir()
            link = root / "linked"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                resolve_project_target("linked", cwd=root)

    def test_create_project_writes_files_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            created = create_project(target, "cli", cwd=root)
            self.assertIn("src/app/cli.py", created)
            self.assertTrue((target / "tests/test_cli.py").is_file())

            with self.assertRaises(ValueError):
                create_project(target, "cli", cwd=root)
            self.assertTrue((target / "src/app/cli.py").is_file())

    def test_create_project_supports_javascript_and_typescript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            js_files = create_project("js-app", "cli", cwd=root, language="javascript")
            ts_files = create_project("ts-app", "api", cwd=root, language="typescript")

            self.assertIn("src/index.js", js_files)
            self.assertEqual(json.loads((root / "ts-app/package.json").read_text())["engines"]["node"], ">=24")
            self.assertTrue((root / "ts-app/src/app.ts").is_file())

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            build_scaffold("web", "sample")

    def test_python_keyword_folder_name_becomes_valid_package(self):
        files = build_scaffold("cli", "class")
        self.assertIn("src/app_class/cli.py", files)

    def test_failed_scaffold_write_removes_only_new_files_and_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "new-app"
            original_open = Path.open

            def fail_on_readme(path, *args, **kwargs):
                if path.name == "README.md":
                    raise OSError("simulated disk error")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", fail_on_readme):
                with self.assertRaises(OSError):
                    create_project(target, "cli", cwd=root)
            self.assertFalse(target.exists())

    def test_partial_scaffold_write_is_removed_after_disk_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "new-app"
            original_open = Path.open

            class FailingWriter:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    self.stream.close()
                    return False

                def write(self, content):
                    self.stream.write(content[:1])
                    raise OSError("simulated partial disk write")

            def fail_mid_write(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return FailingWriter(stream) if path.name == ".gitignore" else stream

            with patch.object(Path, "open", fail_mid_write):
                with self.assertRaisesRegex(OSError, "partial disk write"):
                    create_project(target, "cli", cwd=root)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
