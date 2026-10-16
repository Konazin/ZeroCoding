
from copy import copy

from ..providers.ollama import OllamaProvider
from ..providers.openai_compatible import OpenAICompatibleProvider
from ..providers.llama_cpp import LlamaCppProvider
from .config import Config


def build_provider(config: Config):
    provider = config.active_provider
    if provider.type == "ollama":
        return OllamaProvider(url=provider.base_url, model=provider.model)
    if provider.type == "llama_cpp":
        return LlamaCppProvider(
            api_key=provider.resolved_api_key(),
            api_url=provider.base_url,
            model=provider.model,
        )
    return OpenAICompatibleProvider(
        api_key=provider.resolved_api_key(),
        api_url=provider.base_url,
        model=provider.model,
    )


def build_session_provider(config: Config, provider_name: str, model: str):
    """Build a session-scoped provider without changing saved defaults."""
    runtime_config = copy(config)
    runtime_config.providers = dict(config.providers)
    selected = copy(config.providers[provider_name]) if provider_name in config.providers else None
    if selected is None:
        from .config import ProviderConfig
        selected = ProviderConfig(name=provider_name)
    selected.model = model
    runtime_config.providers[provider_name] = selected
    runtime_config.provider = provider_name
    return build_provider(runtime_config)
