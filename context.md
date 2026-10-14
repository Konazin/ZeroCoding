# ZeroCoding — contexto do projeto

Este arquivo dá contexto rápido a pessoas e agentes que trabalham no repositório. As decisões detalhadas de cada etapa ficam no [roadmap](docs/ROADMAP.md) e nos planos específicos em `docs/`.

## Objetivo

ZeroCoding é um coding agent local em terminal, inspirado nos fluxos de ferramentas de agentes como Claude Code, mas dimensionado para modelos menores e PCs leves ou intermediários. A prioridade é uso sério com contexto controlado, resposta ágil, segurança explícita e pouca infraestrutura.

Máquina de referência: Ryzen 5 4600G, 16 GB de RAM e AMD RX 5700 com 8 GB de VRAM.

## Modelo e runtime atuais

- Modelo de trabalho único: Ornith-1.5-9B Q5_K_M, GGUF denso/full model.
- Arquivo local neste ambiente: `/mnt/jogos/huggingFaceModels/Ornith-1.5-9B-Q5_K_M.gguf`.
- Runtime escolhido: `llama.cpp` `llama-server`, com Vulkan na RX 5700 (`Vulkan0`) e API local OpenAI-compatible.
- ZeroCoding usa alias `ornith-1.5-9b-q5-k-m` no endpoint `http://127.0.0.1:8080/v1`.
- Nesta etapa não há seleção, comparação ou configuração padrão de Gemma, Astra, Luna ou outros modelos. Os modos built-in reutilizam o mesmo Ornith e variam budgets.
- Perfil de coding documentado: temperature 0.6, top-p 0.95, top-k 20, presence penalty 0 e repetition penalty 1. O servidor usa contexto de 8192 e uma slot (`-np 1`) para uso individual. Os valores ficam no comando/configuração do servidor.
- O `llama-server` instalado foi 0.6.0 (build b11429). Seu endpoint `/props` declara `supports_tools: true`, `supports_reasoning_effort: false` e `supports_preserve_reasoning: false` para o template carregado. ZeroCoding encaminha `reasoning_effort`, mas isso não está validado como controle nativo para o Ornith; effort deve ser entendido pelos budgets locais até uma validação futura.
- Smoke local na RX 5700/Vulkan observou aproximadamente 7.05–7.18 GB de VRAM usada (8.57 GB totais), processamento de prompt em 112–123 tokens/s e geração em 17.8–18.9 tokens/s em requests curtas. São observações do smoke, não um benchmark estável. A contagem exata de camadas offloaded não foi confirmada.

## Arquitetura e contratos

- `providers/ollama.py` é legado: mantido só por compatibilidade de configs antigas, sem novas funcionalidades e sem validação contra um servidor Ollama real. O runtime suportado é llama.cpp.
- Runtime principal em Python; TUI de produção em Rich + prompt_toolkit.
- `core/agent.py` monta contexto limitado, chama o provider e executa um loop limitado de ferramentas.
- Providers normalizam texto, tool calls, uso de tokens e dados de reasoning. Raciocínio privado nunca deve aparecer na TUI nem ser salvo em histórico de sessão.
- Leitura, listagem e busca são limitadas ao workspace. Escritas e shell mostram preview e exigem aprovação explícita.
- Plan mode expõe e executa somente ferramentas de leitura; a proteção também existe no executor.
- Preferir dependências pequenas e interfaces testáveis. Evitar frameworks ou subprocessos de modelo dentro do Python quando o servidor local separado resolve o problema.

## Estado do roadmap

- M1 visual/fluxo foi concluído e revisado pelo usuário.
- M2, sobre prompt/contexto, foi declarado concluído pelo usuário em 2026-10-14. Os relatórios em `docs/` ficam como referência; o prompt de produção segue inalterado até uma decisão explícita.
- M3 está liberado, mas só deve começar quando o usuário pedir. Ver `docs/ROADMAP-extension.md` para os itens de revisão e sub-marcos adicionais.

### Preparação do M3 (encerrada em 2026-10-14; M3 não iniciado)

- Baseline: tags locais `m3-baseline` (M2 concluído) e `m3-baseline-2` (após as ressalvas abaixo); `development` sincronizada com `origin/development`, que preserva a linha antiga `9658fd2` apenas no histórico.
- Suíte: `uv run python -m unittest discover -s tests -p 'test_*.py'` com 81 testes passando.
- Ressalvas tratadas: contexto dinâmico opcional (`dynamic_context`, desligado por padrão, não medido); testes de caracterização dos comandos do `cli.py`; `providers/ollama.py` marcado como legado.
- Pendente para o fim do M3 (decisão do usuário): estimativa real de tokens (`/tokenize` do llama-server com fallback) no lugar de ~4 caracteres por token.
- Pendente de medição: ativar `dynamic_context` por padrão só depois de comparar com `scripts/prompt_study.py` usando o servidor Ornith.

## Regras de trabalho

- Trabalhar na branch `development` salvo orientação diferente.
- Preservar alterações locais existentes; nunca descartá-las para limpar o working tree.
- Usar workspace temporário para testes de ferramentas com escrita ou comando e verificar aprovação/Plan.
- Atualizar este arquivo quando uma decisão estrutural mudar, mantendo o roadmap e os relatórios como fontes específicas de cada etapa.
