
import os
from dataclasses import dataclass
from pathlib import Path

from .dotenv import load_env


@dataclass
class Config:
    provider: str
    openai_api_key: str
    openai_api_url: str
    ollama_url: str
    model: str
    memory_path: str
    skills_path: str
    theme: str
    auto_save: bool

    @classmethod
    def load(cls, override_provider=None, env_file=".env"):
        # Load .env file first
        load_env(env_file)

        project_root = Path(__file__).resolve().parents[2]
        config_file = project_root / "config" / "default.yaml"
        values = {
            "provider": "openai",
            "openai_api_key": "",
            "openai_api_url": "https://api.openai.com/v1",
            "ollama_url": "http://localhost:11434",
            "model": "gpt-4o-mini",
            "memory_path": ".zerocoding/memory.db",
            "skills_path": "skills",
            "theme": "dark",
            "auto_save": True,
        }

        if config_file.exists():
            raw = config_file.read_text(encoding="utf-8")
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                values[key] = value

        values["provider"] = override_provider or os.getenv("ZEROCODING_PROVIDER") or values["provider"]
        values["openai_api_key"] = os.getenv("OPENAI_API_KEY", values["openai_api_key"])
        values["openai_api_url"] = os.getenv("OPENAI_API_URL", values["openai_api_url"])
        values["ollama_url"] = os.getenv("OLLAMA_URL", values["ollama_url"])
        values["model"] = os.getenv("ZEROCODING_MODEL", values["model"])
        values["memory_path"] = os.getenv("ZEROCODING_MEMORY_PATH", values["memory_path"])
        values["skills_path"] = os.getenv("ZEROCODING_SKILLS_PATH", values["skills_path"])
        values["theme"] = os.getenv("ZEROCODING_THEME", values["theme"])
        values["auto_save"] = os.getenv("ZEROCODING_AUTO_SAVE", "true").lower() in ("true", "1", "yes")

        return cls(
            provider=values["provider"],
            openai_api_key=values["openai_api_key"],
            openai_api_url=values["openai_api_url"],
            ollama_url=values["ollama_url"],
            model=values["model"],
            memory_path=values["memory_path"],
            skills_path=values["skills_path"],
            theme=values["theme"],
            auto_save=values["auto_save"],
        )
