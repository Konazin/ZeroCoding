"""Fast provider and model readiness checks for first-use flows."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderReadiness:
    status: str
    message: str
    models: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == "connected"


def model_is_available(model: str, available: list[str] | tuple[str, ...]) -> bool:
    wanted = model.strip()
    if wanted in available:
        return True
    return ":" not in wanted and f"{wanted}:latest" in available


def check_provider_readiness(provider, provider_type: str, model: str) -> ProviderReadiness:
    if provider_type == "ollama":
        try:
            models = tuple(provider.list_models())
        except Exception as exc:
            return ProviderReadiness("offline", f"Não foi possível acessar o Ollama: {exc}")
        if not models:
            return ProviderReadiness("no-models", "O Ollama está acessível, mas não há modelos instalados.")
        if not model_is_available(model, models):
            return ProviderReadiness("model-missing", f"O modelo configurado '{model}' não está instalado.", models)
        return ProviderReadiness("connected", "Provider e modelo prontos.", models)

    try:
        if provider.healthcheck():
            return ProviderReadiness("connected", "Provider conectado.")
    except Exception as exc:
        return ProviderReadiness("offline", f"Não foi possível acessar o provider: {exc}")
    return ProviderReadiness("offline", "Provider desconectado. Confira URL e credenciais.")


def readiness_hint(readiness: ProviderReadiness, provider_type: str, model: str) -> str:
    if readiness.ready:
        return ""
    if readiness.status == "offline" and provider_type == "ollama":
        return "Inicie o Ollama com `ollama serve` e tente novamente."
    if readiness.status == "offline":
        return "Confira a URL do provider e a variável de ambiente da chave API."
    if readiness.status == "no-models":
        return "Instale um modelo local, por exemplo `ollama pull qwen2.5-coder:7b`, ou configure outro provider."
    if readiness.status == "model-missing":
        choices = ", ".join(readiness.models)
        return f"Instale `{model}` com `ollama pull {model}` ou escolha um modelo instalado: {choices}."
    return readiness.message
