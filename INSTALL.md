# Instalação ZeroCoding

## Pré-requisitos
- Python 3.10+
- pip (ou python -m pip)
- Node.js 24+ e npm para scaffolds JavaScript/TypeScript
- Linux bubblewrap (`bwrap`) funcional para habilitar `full-access`

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

Ou manualmente instale `rich`, `prompt_toolkit` e `pyyaml`:
```bash
python -m pip install rich prompt_toolkit pyyaml
```

## Configuração

### 1. Copie o arquivo de exemplo
```bash
cp .env.example .env
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
ZEROCODING_MODEL=qwen2.5-coder:7b
ollama pull qwen2.5-coder:7b
```

## Uso

### Modo Interativo (com TUI bonito)
```bash
zerocoding
```

### Enviar uma mensagem
```bash
zerocoding -m "Escreva um script Python que..."
```

### Ver skills disponíveis
```bash
zerocoding --list-skills
```

### Criar um projeto
```bash
zc init ./my-project
```

Escolha Python, JavaScript ou TypeScript, depois `cli` ou `api`, e descreva o projeto. O ZeroCoding verifica provider e modelo, apresenta os arquivos do scaffold e usa o modo de permissão ativo para aprovar a criação.

Durante a geração, o agente altera o módulo principal e o arquivo de testes; não executa comandos. Python API usa FastAPI; JavaScript/TypeScript API usa Fastify e Node.js 24+. Verificações e instalação de dependências têm aprovações próprias. Se uma verificação falhar, o agente pode tentar uma correção e pede nova aprovação antes de repetir.

### Modos de permissão

- `manual` (padrão): confirma cada escrita e comando.
- `approve-for-me`: o provider ativo revisa escritas locais em uma chamada separada; falha ou resposta inválida nega a ação.
- `full-access`: remove prompts para ações locais e executa comandos em bubblewrap, com rede desativada. Só fica disponível quando o auto-teste do sandbox passa.

Use `/permissions` dentro da TUI. Rede, MCP e instalação de dependências sempre pedem confirmação humana.

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
ZEROCODING_SKILLS_PATH=skills      # Diretório de skills
ZEROCODING_THEME=dark              # Tema: dark, light
ZEROCODING_AUTO_SAVE=true          # Auto-salvar conversa
```

### MCP opcional
```bash
python -m pip install -e '.[mcp]'
```
Configure os servidores `stdio` em `~/.zerocoding/config.yaml`, na chave `mcp_servers`.

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
