# Instalação do ZeroCoding

ZeroCoding requer Python 3.10 ou mais recente e um endpoint compatível com a API OpenAI. O runtime recomendado é `llama-server`; a instalação do modelo e os parâmetros de Vulkan estão no [README](README.md#local-ornith-with-llamacpp).

## Instalar a partir do checkout

Com [uv](https://docs.astral.sh/uv/), instale o comando como ferramenta:

```bash
git clone <url-do-repositorio>
cd ZeroCoding
uv tool install .
```

Para desenvolver ou executar a suíte automatizada:

```bash
uv sync --locked
uv run pytest -q
```

Também é possível instalar com pip:

```bash
python -m pip install .
```

A configuração padrão e as skills são incluídas no pacote. O primeiro uso também pode ser feito fora do diretório do checkout.

## Configurar o servidor

O padrão aponta para `http://127.0.0.1:8080/v1`. Inicie o `llama-server` com um alias de modelo e confira a configuração:

```bash
zc doctor
```

Para usar outro endereço ou alias, edite `~/.zerocoding/config.yaml`:

```yaml
provider: llama_cpp_local
providers:
  llama_cpp_local:
    type: llama_cpp
    base_url: http://127.0.0.1:8080/v1
    model: ornith-1.5-9b-q5-k-m
```

O valor de `model` deve corresponder ao alias exposto pelo servidor. `zc doctor` verifica conectividade, contexto, slots, tokenizer e template sem gerar uma resposta do modelo.

## Usar

```bash
zc                         # TUI interativa
zc -m "Explique este projeto"  # resposta única
zc --list-skills           # listar skills disponíveis
```

Streaming é opcional e permanece desligado até passar pela comparação de qualidade do M7. Para habilitá-lo, defina `streaming_enabled: true` na configuração.

Na TUI, `/help` lista os comandos. `/provider test` verifica o endpoint atual. Escritas e comandos continuam exigindo aprovação explícita.
