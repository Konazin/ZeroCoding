
from ..providers.ollama import OllamaProvider
from ..providers.openai_compatible import OpenAICompatibleProvider
from .config import Config


def build_provider(config: Config):
    provider = config.active_provider
    if provider.type == "ollama":
        return OllamaProvider(url=provider.base_url, model=provider.model)
    return OpenAICompatibleProvider(
        api_key=provider.resolved_api_key(),
        api_url=provider.base_url,
        model=provider.model,
    )
