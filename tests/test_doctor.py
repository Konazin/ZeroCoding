import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from zerocoding.core.config import Config, ConfigManager, ProviderConfig
from zerocoding.core.doctor import Check, print_report, run_doctor


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "skills").mkdir()
        self.manager = ConfigManager(user_config_path=self.root / "config.yaml",
                                     env_file=str(self.root / "missing.env"))
        self.config = Config(
            provider="local",
            providers={"local": ProviderConfig(name="local", type="llama_cpp",
                                                 base_url="http://fake.local:8080/v1", model="ornith")},
            skills_path=str(self.root / "skills"),
            plugins_path=str(self.root / "plugins"),
            max_input_tokens=4096,
            max_output_tokens=1024,
        )

    def request_ok(self, url, *, method="GET", payload=None, api_key="", timeout=3):
        if url.endswith("/health"):
            return "ok"
        if url.endswith("/props"):
            return {
                "model_alias": "ornith",
                "default_generation_settings": {"n_ctx": 8192},
                "total_slots": 1,
                "chat_template_caps": {"supports_reasoning_effort": False},
            }
        if url.endswith("/tokenize"):
            self.assertEqual(method, "POST")
            return {"tokens": [1, 2, 3]}
        if url.endswith("/apply-template"):
            self.assertEqual(method, "POST")
            self.assertTrue(payload["tools"])
            return {"prompt": "rendered prompt"}
        self.fail(f"Unexpected doctor request: {url}")

    def test_checks_llama_server_endpoints_without_chat_completion(self):
        requested = []

        def request(url, **kwargs):
            requested.append(url)
            return self.request_ok(url, **kwargs)

        checks = run_doctor(self.config, self.manager, self.root, request=request)
        by_name = {check.name: check for check in checks}

        self.assertEqual(by_name["Server health"].status, "ok")
        self.assertEqual(by_name["Model alias"].status, "ok")
        self.assertEqual(by_name["Slots"].status, "ok")
        self.assertEqual(by_name["Context size"].status, "ok")
        self.assertEqual(by_name["Tokenizer"].status, "ok")
        self.assertEqual(by_name["Chat template"].status, "ok")
        self.assertEqual(by_name["Reasoning effort"].status, "warn")
        self.assertTrue(all("chat/completions" not in url for url in requested))

    def test_reports_non_default_slots_and_context_below_budget(self):
        def request(url, **kwargs):
            if url.endswith("/health"):
                return "ok"
            if url.endswith("/props"):
                return {"model_alias": "wrong", "default_generation_settings": {"n_ctx": 4096},
                        "total_slots": 4, "chat_template_caps": {}}
            if url.endswith("/tokenize"):
                return {"tokens": [1]}
            if url.endswith("/apply-template"):
                return {"prompt": "rendered"}
            raise AssertionError(url)

        checks = {check.name: check for check in run_doctor(self.config, self.manager, self.root, request=request)}

        self.assertEqual(checks["Slots"].status, "warn")
        self.assertEqual(checks["Model alias"].status, "warn")
        self.assertEqual(checks["Context size"].status, "fail")
        self.assertIn("reduce", checks["Context size"].remedy)

    def test_missing_optional_endpoints_are_warnings_and_health_is_blocking(self):
        def request(url, **kwargs):
            if url.endswith("/health"):
                raise OSError("connection refused")
            raise OSError("endpoint missing")

        checks = {check.name: check for check in run_doctor(self.config, self.manager, self.root, request=request)}

        self.assertEqual(checks["Server health"].status, "fail")
        self.assertEqual(checks["Tokenizer"].status, "warn")
        self.assertEqual(checks["Chat template"].status, "warn")

    def test_validates_hooks_plugins_and_starts_allowlisted_fake_mcp_server(self):
        fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
        self.config.hooks = [{"event": "invalid", "command": "true"}]
        self.config.plugins_enabled = ["missing-plugin"]
        self.config.mcp = {"servers": {"fake": {
            "command": [sys.executable, str(fixture)],
            "tools": {"echo": {"read_only": True}},
        }}}

        checks = {check.name: check for check in run_doctor(
            self.config, self.manager, self.root, request=self.request_ok
        )}

        self.assertEqual(checks["Hooks"].status, "fail")
        self.assertEqual(checks["Plugins"].status, "fail")
        self.assertEqual(checks["MCP"].status, "ok")
        self.assertIn("1 allowlisted tool", checks["MCP"].detail)

    def test_report_exit_code_only_fails_for_blocking_checks(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=False)
        self.assertEqual(print_report([], console), 0)
        self.assertEqual(print_report([
            Check("Slots", "warn", "4 slots", "Use -np 1"),
        ], console), 0)
        self.assertEqual(print_report([
            Check("Health", "fail", "offline", "Start server"),
        ], console), 1)
        self.assertIn("Start server", output.getvalue())

    def test_cli_doctor_does_not_construct_or_call_a_provider(self):
        from zerocoding import cli
        from zerocoding.core.doctor import Check

        class Manager:
            def load(self, override_provider=None):
                return self

        with patch.object(cli, "load_env"), patch.object(cli, "ConfigManager", return_value=Manager()), \
                patch("zerocoding.core.doctor.run_doctor", return_value=[Check("Config", "ok", "valid")]), \
                patch("zerocoding.core.doctor.print_report", return_value=0) as report, \
                patch.object(cli, "build_provider") as build_provider:
            self.assertEqual(cli.main(["doctor"]), 0)
        report.assert_called_once()
        build_provider.assert_not_called()

    def test_cli_doctor_reports_invalid_configuration_without_provider_setup(self):
        from zerocoding import cli

        class BrokenManager:
            def load(self, override_provider=None):
                raise ValueError("invalid YAML")

        with patch.object(cli, "load_env"), patch.object(cli, "ConfigManager", return_value=BrokenManager()), \
                patch("zerocoding.core.doctor.print_report", return_value=1) as report, \
                patch.object(cli, "build_provider") as build_provider:
            self.assertEqual(cli.main(["doctor"]), 1)
        self.assertEqual(report.call_args.args[0][0].status, "fail")
        build_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
