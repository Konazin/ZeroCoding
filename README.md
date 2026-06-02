
# ZeroCoding

Assistente pessoal de codificação minimalista com interface visual (TUI) tipo Claude, suporte a skills, memória de conversa e integração com OpenAI ou Ollama.

## Características

- 🎨 **Interface Visual Bonita** - TUI com theme customizável (fallback em texto puro)
- 🤖 **Vários Providers** - OpenAI, Ollama ou qualquer API compatível
- 💾 **Memória Persistente** - Usa SQLite para guardar conversas
- 🛠️ **Sistema de Skills** - Carregue skills do diretório `skills/`
- ⚙️ **Configuração Simples** - Via `.env` ou variáveis de ambiente
- 🚀 **CLI Completa** - Modo interativo ou linha de comando

## Instalação Rápida

```bash
# Clone ou entre no diretório
cd /home/kona/programas/zerocoding

# Instale com dependências (rico para UI)
python -m pip install -e .

# Copie config de exemplo
cp env.example .env

# Configure sua chave API
# nano .env
```

## Uso

### Modo Interativo (Recomendado)
```bash
zerocoding
```
Você verá um avatar bonito e poderá conversar livremente.

### Enviar Mensagem Única
```bash
zerocoding -m "Escreva um script Python para listar arquivos"
```

### Ver Skills Disponíveis
```bash
zerocoding --list-skills
```

### Listar Mais Opções
```bash
zerocoding --help
```

## Configuração

Copie `env.example` para `.env` e configure:

```bash
# Provider a usar: openai ou ollama
ZEROCODING_PROVIDER=openai

# OpenAI
OPENAI_API_KEY=sk-seu-chave-aqui
OPENAI_API_URL=https://api.openai.com/v1

# Ollama (local)
OLLAMA_URL=http://localhost:11434

# Modelo
ZEROCODING_MODEL=gpt-4o-mini

# Diretório de skills
ZEROCODING_SKILLS_PATH=skills

# Memória
ZEROCODING_MEMORY_PATH=.zerocoding/memory.db
```

## Comandos Interativos

No modo interativo, você pode:
- Digitar uma pergunta normalmente
- `/exit` ou `/quit` - Sair
- `/clear` - Limpar tela
- `/skills` - Listar skills
- `/help` - Mostrar comandos rápidos
- `Ctrl+C` - Interromper

## Estrutura

```
zerocoding/
├── src/zerocoding/
│   ├── cli.py              # CLI e entry point
│   ├── core/
│   │   ├── agent.py        # Agent principal
│   │   ├── config.py       # Configuração
│   │   ├── dotenv.py       # Carregador .env
│   │   ├── prompt.py       # Builder de prompts
│   │   └── ...
│   ├── tui/
│   │   └── app.py          # Interface visual
│   ├── memory/
│   │   └── sqlite.py       # Banco de dados
│   ├── providers/
│   │   ├── base.py
│   │   ├── openai_compatible.py
│   │   └── ollama.py
│   ├── skills/
│   │   ├── loader.py
│   │   └── parser.py
│   └── tools/              # Shell, git, grep, files
├── skills/                 # Seu local de skills (.md)
├── config/
│   └── default.yaml
├── env.example
└── .env
```

## Dependências

- `rich` - Para interface visual bonita (opcional, fallback para texto)
- `prompt_toolkit` - Para autocompletar comandos e navegação com ↑/↓ no prompt

Instale com: `python -m pip install rich prompt_toolkit`

## Exemplos

### Usar com Ollama local
```bash
export ZEROCODING_PROVIDER=ollama
export OLLAMA_URL=http://localhost:11434
zerocoding -m "Escreva um Hello World em Python"
```

### Usar com OpenAI
```bash
export OPENAI_API_KEY=sk-sua-chave
zerocoding -m "Qual é a capital do Brasil?"
```

### Sem interface visual
```bash
zerocoding --no-tui -m "Sua pergunta"
```

## Desenvolvimento

```bash
# Executar testes
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'

# Verificar sintaxe
python -m py_compile $(find src -name '*.py')
```

## Licença

MIT

## Mais Informações

Veja [INSTALL.md](INSTALL.md) para instruções detalhadas de instalação.
