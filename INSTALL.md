# Instalação ZeroCoding

## Pré-requisitos
- Python 3.10+
- pip (ou python -m pip)

## Instalação Rápida

### 1. Clone o repositório
```bash
cd /home/kona/programas/zerocoding
```

### 2. Crie um ambiente virtual (recomendado)
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

### 3. Instale as dependências
```bash
python -m pip install --upgrade pip setuptools
python -m pip install -e .
```

Ou manualmente instale `rich` e `prompt_toolkit`:
```bash
python -m pip install rich prompt_toolkit
```

## Configuração

### 1. Copie o arquivo de exemplo
```bash
cp env.example .env
```

### 2. Configure suas credenciais no `.env`

**Para OpenAI:**
```bash
ZEROCODING_PROVIDER=openai
OPENAI_API_KEY=sk-seu-chave-aqui
```

**Para Ollama (local):**
```bash
ZEROCODING_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
ZEROCODING_MODEL=llama2
```

## Uso

### Modo Interativo (com TUI bonito)
```bash
zerocoding
```

### Modo Interativo (sem TUI)
```bash
zerocoding --no-tui
```

### Enviar uma mensagem
```bash
zerocoding -m "Escreva um script Python que..."
```

### Ver skills disponíveis
```bash
zerocoding --list-skills
```

### Limpar memória
```bash
zerocoding --clear-memory
```

## Comandos dentro do modo interativo

- `/exit` / `/quit` / `/q` - Sair
- `/clear` - Limpar tela
- `/skills` - Listar skills disponíveis
- `/help` - Mostrar ajuda rápida
- Ou simplesmente digite sua pergunta

## Variáveis de Ambiente

```bash
ZEROCODING_PROVIDER=openai          # Provider: openai ou ollama
OPENAI_API_KEY=sk-...              # Chave da API OpenAI
OPENAI_API_URL=https://...         # URL customizada (ex: LM Studio)
OLLAMA_URL=http://...              # URL do Ollama
ZEROCODING_MODEL=gpt-4o-mini       # Modelo a usar
ZEROCODING_MEMORY_PATH=.zerocoding/memory.db
ZEROCODING_SKILLS_PATH=skills      # Diretório de skills
ZEROCODING_THEME=dark              # Tema: dark, light
ZEROCODING_AUTO_SAVE=true          # Auto-salvar conversa
```

## Solução de Problemas

### Erro: "No module named 'rich'"
Instale: `python -m pip install rich`

### Erro: "OPENAI_API_KEY is required"
- Configure `.env` com sua chave
- Ou execute: `export OPENAI_API_KEY=sk-seu-chave`

### Erro: "Connection refused" (Ollama)
- Certifique-se que Ollama está rodando: `ollama serve`
- Ou use OpenAI: `zerocoding --provider openai`

## Suporte

Verifique o arquivo `README.md` para mais informações.
