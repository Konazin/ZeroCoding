# Extensão do roadmap do ZeroCoding

Este documento **complementa** [`ROADMAP.md`](ROADMAP.md) sem alterá-lo. Os marcos M1–M5 permanecem como definidos lá; aqui ficam a revisão do estado atual (a partir de `context.md`), os pontos que merecem revisão e os sub-marcos adicionais propostos.

## 1. O que pode continuar agora

- **Fechar o M2:** o usuário revisa `prompt-study.md`, `prompt-effort-study.md` e `model-baseline.md` e declara o marco concluído. É o único bloqueio para o M3.
- **Integração do Ornith:** validar servidor, alias do modelo e `/props` no fluxo real da TUI, sem mudar o prompt de produção.
- **Higiene do repositório:** commitar por partes o que está sem commit (`tools.py`, `events.py`, `history.py`, `demo_*`, `docs/`, `scripts/`, testes novos, `uv.lock`).
- **Ferramentas de desenvolvimento:** adicionar grupo `dev` com pytest (hoje `uv run pytest` falha) e documentar no README.
- **`context.md`:** atualizar quando o estado mudar, conforme a regra do próprio arquivo.

## 2. O que precisa de revisão

| Área | Problema | Ação proposta | Marco |
|---|---|---|---|
| Estimativa de tokens (`agent.estimate_tokens`) | 4 caracteres por token erra com código e português; o último recurso de `fit_messages` descarta quase tudo | Usar a contagem real do `/tokenize` do llama-server quando disponível, com fallback; medir o erro | M3 |
| `run_command` | A única barreira é a aprovação; sem validação de argumentos nem limite de ambiente | Política de comandos (permissão/negação, ambiente mínimo, limite de saída) | M4 |
| `write_file` | Substitui o arquivo inteiro; modelo pequeno pode truncar | Adicionar `edit_file` (trecho antigo/novo) mantendo o diff e a aprovação | M4 |
| Effort nativo | `reasoning_effort` não validado no Ornith (`supports_reasoning_effort: false`) | Manter só os budgets locais; registrar a decisão e testar thinking no template | M3 |
| Respostas vazias | O Qwen3.5 devolveu resposta final vazia em 6 tentativas; o agente tenta de novo apenas 1 vez | Investigar chat template/reasoning no adapter antes de ampliar modelos | M3 |
| Estudos do M2 | Só 2 repetições por condição, sem RAM/VRAM, avaliação cega limitada no cenário direto | Repetir com 3+ repetições e medir memória | M5 |
| Código duplicado | `approve`/`_approve` em `tools.py`; retry e resposta vazia repetidos em `agent.py` | Limpar na decomposição | M3 |
| Testes | Falta cobertura da TUI, de `llama_cpp` e do sandbox de caminhos | Ampliar (aprovação/recusa, caminhos fora do workspace, isolamento de sessão) | M4 |
| `demo_*` em `src/` | Protótipos misturados ao pacote de produção | Decidir entre manter ou migrar para `scripts/` | M3 |

## 3. Melhorias candidatas

- Contexto do projeto carregado só quando necessário, com custo em tokens medido por bloco.
- Skills e schemas de ferramentas dinâmicos por tarefa.
- Compactação do histórico (resumo) em vez de descartar mensagens antigas.
- Métricas locais por turno (tokens reais, latência, erros) em `.zerocoding/`, sem versionar respostas.
- Streaming real na TUI, se o provedor suportar.
- Cancelamento (Ctrl+C) do turno do agente.

## 4. Sub-marcos adicionais

### M2.5 — Encerramento do M2 e base estável
Pré-requisito do M3.

- Revisão e declaração do M2 pelo usuário; commits organizados; dev deps; `context.md` atualizado.
- **Saída:** `uv run pytest` passa em ambiente limpo e o M2 está marcado como concluído pelo usuário.

### M3 / M4 / M5 — itens extras
Os itens das seções 1 e 2 marcados com M3, M4 ou M5 entram como entregas adicionais nesses marcos, sem substituir as já definidas.

### M4.5 — Qualidade de uso diário
- Compactação de histórico, contexto dinâmico de skills/ferramentas, cancelamento de turno e logs locais de métricas.
- **Saída:** sessões longas permanecem dentro do orçamento sem perder o pedido atual; métricas por turno disponíveis localmente.

### M6 — Extensibilidade (condicional)
- MCP, subagentes, plugins e hooks, somente se M3–M5 provarem necessidade e custo aceitável.

## Ordem recomendada

M2.5 → M3 → M4 → M4.5 → M5 → (M6 se justificado). M4.5 pode andar em paralelo ao fim do M4 se não alterar contratos.

Comparar outros modelos além do Ornith só entra no M5 se o `context.md` for atualizado para permitir (hoje o Ornith é o modelo único de trabalho).
