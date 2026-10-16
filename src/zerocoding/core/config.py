import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .command_policy import CommandPolicy
from .dotenv import load_env

try:
    import yaml
except ImportError:  # pragma: no cover - fallback for minimal installs
    yaml = None


DEFAULT_PROVIDER = "llama_cpp_local"
DEFAULT_USER_CONFIG = Path("~/.zerocoding/config.yaml").expanduser()


@dataclass
class ProviderConfig:
    name: str
    type: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "deepseek-coder-v2"
    api_key: str = ""
    api_key_env: str = ""

    @classmethod
    def from_dict(cls, name: str, values: dict[str, Any]):
        return cls(
            name=name,
            type=str(values.get("type", "ollama")),
            base_url=str(values.get("base_url", values.get("url", "http://localhost:11434"))),
            model=str(values.get("model", "deepseek-coder-v2")),
            api_key=str(values.get("api_key", "")),
            api_key_env=str(values.get("api_key_env", "")),
        )

    def resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.getenv(self.api_key_env, "")
        return ""

    def to_dict(self) -> dict[str, str]:
        data = {
            "type": self.type,
            "base_url": self.base_url,
            "model": self.model,
        }
        if self.api_key_env:
            data["api_key_env"] = self.api_key_env
        if self.api_key:
            data["api_key"] = self.api_key
        return data


@dataclass
class ModeConfig:
    name: str
    provider: str = DEFAULT_PROVIDER
    model: str = "deepseek-coder-v2"
    skills: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, values: dict[str, Any]):
        return cls(
            name=name,
            provider=str(values.get("provider", DEFAULT_PROVIDER)),
            model=str(values.get("model", "deepseek-coder-v2")),
            skills=list(values.get("skills") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "skills": list(self.skills),
        }


@dataclass(frozen=True)
class EffortProfile:
    max_output_tokens: int
    max_tool_rounds: int

    @classmethod
    def from_dict(cls, values: dict[str, Any], defaults: "EffortProfile") -> "EffortProfile":
        values = values or {}
        return cls(
            max_output_tokens=max(128, int(values.get("max_output_tokens", defaults.max_output_tokens))),
            max_tool_rounds=max(1, min(12, int(values.get("max_tool_rounds", defaults.max_tool_rounds)))),
        )

    def to_dict(self) -> dict[str, int]:
        return {"max_output_tokens": self.max_output_tokens, "max_tool_rounds": self.max_tool_rounds}


DEFAULT_EFFORT_PROFILES = {
    "low": EffortProfile(512, 3),
    "medium": EffortProfile(1024, 6),
    "high": EffortProfile(2048, 8),
}


@dataclass
class Config:
    provider: str = DEFAULT_PROVIDER
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    mode: str = "code"
    modes: dict[str, ModeConfig] = field(default_factory=dict)
    memory_path: str = ".zerocoding/memory.db"
    skills_path: str = "skills"
    theme: str = "purple"
    auto_save: bool = True
    max_input_tokens: int = 4096
    max_output_tokens: int = 1024
    max_tool_rounds: int = 6
    dynamic_context: bool = False
    command_policy: CommandPolicy = field(default_factory=CommandPolicy)
    effort_profiles: dict[str, EffortProfile] = field(default_factory=lambda: dict(DEFAULT_EFFORT_PROFILES))

    @property
    def active_provider(self) -> ProviderConfig:
        if self.provider not in self.providers:
            self.providers[self.provider] = ProviderConfig(name=self.provider)
        return self.providers[self.provider]

    @property
    def model(self) -> str:
        return self.active_provider.model

    @model.setter
    def model(self, value: str) -> None:
        self.active_provider.model = value

    @property
    def ollama_url(self) -> str:
        return self.active_provider.base_url

    @property
    def openai_api_url(self) -> str:
        return self.active_provider.base_url

    @property
    def openai_api_key(self) -> str:
        return self.active_provider.resolved_api_key()

    @classmethod
    def load(cls, override_provider=None, env_file=".env"):
        return ConfigManager(env_file=env_file).load(override_provider=override_provider)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "providers": {name: provider.to_dict() for name, provider in self.providers.items()},
            "mode": self.mode,
            "modes": {name: mode.to_dict() for name, mode in self.modes.items()},
            "memory_path": self.memory_path,
            "skills_path": self.skills_path,
            "theme": self.theme,
            "auto_save": self.auto_save,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_tool_rounds": self.max_tool_rounds,
            "dynamic_context": self.dynamic_context,
            "command_policy": self.command_policy.to_dict(),
            "effort_profiles": {name: profile.to_dict() for name, profile in self.effort_profiles.items()},
        }


class ConfigManager:
    def __init__(self, user_config_path: str | Path = DEFAULT_USER_CONFIG, env_file: str = ".env"):
        self.user_config_path = Path(user_config_path).expanduser()
        self.env_file = env_file

    def load(self, override_provider=None) -> Config:
        load_env(self.env_file)
        user_data = self._read_yaml(self.user_config_path)
        data = self._default_data()
        data = self._deep_merge(data, user_data)
        self._apply_env(data)

        provider_name = override_provider or data.get("provider") or DEFAULT_PROVIDER
        providers = {
            name: ProviderConfig.from_dict(name, values or {})
            for name, values in (data.get("providers") or {}).items()
        }
        modes = {
            name: ModeConfig.from_dict(name, values or {})
            for name, values in (data.get("modes") or {}).items()
        }
        if not providers:
            providers[DEFAULT_PROVIDER] = ProviderConfig(name=DEFAULT_PROVIDER)
        if not modes:
            modes = self._default_modes()
        if override_provider is None and provider_name in {"ollama", "openai"}:
            provider_name = self._legacy_provider_name(provider_name, providers)
        if provider_name not in providers:
            providers[provider_name] = ProviderConfig(name=provider_name)

        effort_profiles = self._load_effort_profiles(data, user_data)
        medium = effort_profiles["medium"]
        return Config(
            provider=provider_name,
            providers=providers,
            mode=str(data.get("mode", "code")),
            modes=modes,
            memory_path=str(data.get("memory_path", ".zerocoding/memory.db")),
            skills_path=str(data.get("skills_path", "skills")),
            theme=str(data.get("theme", "purple")),
            auto_save=self._as_bool(data.get("auto_save", True)),
            max_input_tokens=max(256, int(data.get("max_input_tokens", 4096))),
            max_output_tokens=medium.max_output_tokens,
            max_tool_rounds=medium.max_tool_rounds,
            dynamic_context=self._as_bool(data.get("dynamic_context", False)),
            command_policy=CommandPolicy.from_dict(data.get("command_policy")),
            effort_profiles=effort_profiles,
        )

    @staticmethod
    def _load_effort_profiles(data: dict[str, Any], user_data: dict[str, Any]) -> dict[str, EffortProfile]:
        defaults = dict(DEFAULT_EFFORT_PROFILES)
        legacy_limits = "effort_profiles" not in user_data and any(
            key in user_data for key in ("max_output_tokens", "max_tool_rounds")
        )
        if legacy_limits:
            medium_output = max(128, int(data.get("max_output_tokens", 1024)))
            medium_rounds = max(1, min(12, int(data.get("max_tool_rounds", 6))))
            defaults = {
                "low": EffortProfile(max(128, medium_output // 2), max(1, (medium_rounds + 1) // 2)),
                "medium": EffortProfile(medium_output, medium_rounds),
                "high": EffortProfile(medium_output * 2, min(12, medium_rounds + 2)),
            }
        raw_profiles = {} if legacy_limits else data.get("effort_profiles") or {}
        return {
            name: EffortProfile.from_dict(raw_profiles.get(name, {}), defaults[name])
            for name in ("low", "medium", "high")
        }

    def save(self, config: Config) -> None:
        self.user_config_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_yaml(self.user_config_path, config.to_dict())

    def _default_data(self) -> dict[str, Any]:
        project_root = Path(__file__).resolve().parents[3]
        data = self._read_yaml(project_root / "config" / "default.yaml")
        if data.get("providers"):
            return data

        provider = data.get("provider", DEFAULT_PROVIDER)
        if provider == DEFAULT_PROVIDER:
            model = "ornith-1.5-9b-q5-k-m"
            return {
                "provider": DEFAULT_PROVIDER,
                "providers": {
                    DEFAULT_PROVIDER: {
                        "type": "llama_cpp",
                        "base_url": "http://127.0.0.1:8080/v1",
                        "model": model,
                    }
                },
                "mode": data.get("mode", "code"),
                "modes": self._default_modes_data(),
                "memory_path": data.get("memory_path", ".zerocoding/memory.db"),
                "skills_path": data.get("skills_path", "skills"),
                "theme": data.get("theme", "purple"),
                "auto_save": data.get("auto_save", True),
                "max_input_tokens": data.get("max_input_tokens", 4096),
                "max_output_tokens": data.get("max_output_tokens", 1024),
                "max_tool_rounds": data.get("max_tool_rounds", 6),
            }
        legacy_type = "ollama" if provider == "ollama" else "openai_compatible"
        return {
            "provider": DEFAULT_PROVIDER if provider == "ollama" else "openai_default",
            "providers": {
                "ollama_local": {
                    "type": "ollama",
                    "base_url": data.get("ollama_url", "http://localhost:11434"),
                    "model": data.get("model", "deepseek-coder-v2"),
                },
                "openai_default": {
                    "type": legacy_type,
                    "base_url": data.get("openai_api_url", "https://api.openai.com/v1"),
                    "api_key_env": "OPENAI_API_KEY",
                    "model": data.get("model", "gpt-4o-mini"),
                },
            },
            "mode": data.get("mode", "code"),
            "modes": self._default_modes_data(),
            "memory_path": data.get("memory_path", ".zerocoding/memory.db"),
            "skills_path": data.get("skills_path", "skills"),
            "theme": data.get("theme", "purple"),
            "auto_save": data.get("auto_save", True),
        }

    def _default_modes(self) -> dict[str, ModeConfig]:
        return {name: ModeConfig.from_dict(name, values) for name, values in self._default_modes_data().items()}

    def _default_modes_data(self) -> dict[str, Any]:
        provider = DEFAULT_PROVIDER
        model = "ornith-1.5-9b-q5-k-m"
        return {
            "code": {"provider": provider, "model": model, "skills": []},
            "reason": {"provider": provider, "model": model, "skills": []},
            "fast": {"provider": provider, "model": model, "skills": []},
            "smart": {"provider": provider, "model": model, "skills": []},
        }

    def _apply_env(self, data: dict[str, Any]) -> None:
        providers = data.setdefault("providers", {})
        if os.getenv("OLLAMA_URL"):
            providers.setdefault("ollama_local", {})["base_url"] = os.getenv("OLLAMA_URL")
        if os.getenv("OPENAI_API_URL"):
            providers.setdefault("openai_default", {})["base_url"] = os.getenv("OPENAI_API_URL")
        if os.getenv("OPENAI_API_KEY"):
            providers.setdefault("openai_default", {})["api_key"] = os.getenv("OPENAI_API_KEY")
        if os.getenv("ZEROCODING_MODEL"):
            active = data.get("provider", DEFAULT_PROVIDER)
            providers.setdefault(active, {})["model"] = os.getenv("ZEROCODING_MODEL")
        env_map = {
            "ZEROCODING_PROVIDER": "provider",
            "ZEROCODING_MEMORY_PATH": "memory_path",
            "ZEROCODING_SKILLS_PATH": "skills_path",
            "ZEROCODING_THEME": "theme",
        }
        for env_name, key in env_map.items():
            if os.getenv(env_name):
                data[key] = os.getenv(env_name)
        if os.getenv("ZEROCODING_AUTO_SAVE"):
            data["auto_save"] = os.getenv("ZEROCODING_AUTO_SAVE")

    def _legacy_provider_name(self, name: str, providers: dict[str, ProviderConfig]) -> str:
        if name == "ollama":
            return "ollama_local" if "ollama_local" in providers else name
        return "openai_default" if "openai_default" in providers else name

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        if yaml:
            return yaml.safe_load(raw) or {}
        return self._read_simple_yaml(raw)

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        if yaml:
            path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")
            return
        path.write_text(self._write_simple_yaml(data), encoding="utf-8")

    def _read_simple_yaml(self, raw: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
        for line in raw.splitlines():
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            indent = len(line) - len(line.lstrip())
            key, value = line.strip().split(":", 1)
            while stack and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1]
            value = value.strip().strip('"').strip("'")
            if value == "":
                parent[key] = {}
                stack.append((indent, parent[key]))
            else:
                parent[key] = self._coerce(value)
        return result

    def _write_simple_yaml(self, data: dict[str, Any], indent: int = 0) -> str:
        lines = []
        for key, value in data.items():
            prefix = " " * indent
            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                lines.append(self._write_simple_yaml(value, indent + 2).rstrip())
            else:
                lines.append(f'{prefix}{key}: "{value}"' if isinstance(value, str) else f"{prefix}{key}: {value}")
        return "\n".join(lines) + "\n"

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _coerce(self, value: str) -> Any:
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        return value

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"true", "1", "yes", "on"}
