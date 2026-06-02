
from ..providers.ollama import OllamaProvider
from ..providers.openai_compatible import OpenAICompatibleProvider
from .config import Config


def build_provider(config: Config):
    if config.provider == "ollama":
        return OllamaProvider(url=config.ollama_url, model=config.model)
    return OpenAICompatibleProvider(
        api_key=config.openai_api_key,
        api_url=config.openai_api_url,
        model=config.model,
    )
