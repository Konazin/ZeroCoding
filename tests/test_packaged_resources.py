import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from importlib import resources


REPOSITORY = Path(__file__).resolve().parents[1]


class TestInstalledPackageResources(unittest.TestCase):
    def test_packaged_defaults_match_repository_sources(self):
        package = resources.files("zerocoding").joinpath("data")
        self.assertEqual(
            package.joinpath("default.yaml").read_text(encoding="utf-8"),
            (REPOSITORY / "config" / "default.yaml").read_text(encoding="utf-8"),
        )
        packaged_skills = package.joinpath("skills")
        self.assertEqual(
            {path.name for path in packaged_skills.iterdir()},
            {path.name for path in (REPOSITORY / "skills").glob("*.md")},
        )
        for source in (REPOSITORY / "skills").glob("*.md"):
            self.assertEqual(
                packaged_skills.joinpath(source.name).read_text(encoding="utf-8"),
                source.read_text(encoding="utf-8"),
            )

    def test_package_defaults_and_skills_load_outside_the_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            site_packages = temp_root / "site-packages"
            site_packages.mkdir()
            shutil.copytree(REPOSITORY / "src" / "zerocoding", site_packages / "zerocoding")
            isolated_cwd = temp_root / "workspace"
            isolated_cwd.mkdir()
            script = (
                "from pathlib import Path; import zerocoding; "
                "from zerocoding.core.config import ConfigManager; "
                "from zerocoding.skills.loader import load_skills; "
                "assert Path(zerocoding.__file__).resolve().is_relative_to(Path.cwd().parent / 'site-packages'); "
                "config = ConfigManager(user_config_path=Path.cwd() / 'missing.yaml').load(); "
                "assert config.provider == 'llama_cpp_local'; "
                "skills = load_skills(config.skills_path); "
                "assert {'python', 'java', 'linux', 'qa', 'spring'} <= {skill.name for skill in skills}"
            )
            environment = dict(os.environ)
            for key in list(environment):
                if key.startswith("ZEROCODING_") or key in {"OLLAMA_URL", "OPENAI_API_URL"}:
                    environment.pop(key)
            environment["PYTHONPATH"] = str(site_packages)
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=isolated_cwd, env=environment,
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
