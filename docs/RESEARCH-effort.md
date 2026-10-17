# Pesquisa: effort real em modelos locais (2026-10-17)

## Problema

Hoje `effort` só muda `max_tokens` e o número de rodadas de ferramenta. Em modelos que raciocinam isso não funciona, porque o raciocínio oculto consome o mesmo `max_tokens` da resposta.

O template do Ornith 1.5 (estilo Qwen3.5) termina o prompt em `<think>\n` (`enable_thinking` indefinido). Ou seja, **o modelo pensa em todo turno**, e o servidor só esconde isso com `--reasoning-format deepseek`.

## Medição no hardware-alvo

Ornith 9B Q5_K_M, llama.cpp b11681, mesma pergunta de código curta, `scripts/effort_probe.py`:

| Pedido | Tokens de saída | Raciocínio (chars) | Resposta (chars) | Tempo |
|---|---:|---:|---:|---:|
| padrão (pensa) | 1370 | 4000 | 859 | 57,6 s |
| `enable_thinking=false` | 345 | 0 | 1133 | 14,4 s |
| `reasoning_effort=none` | 409 | 0 | 1497 | 17,0 s |
| `reasoning_budget_tokens=512` | 744 | 1827 | 773 | 31,4 s |
| `reasoning_budget_tokens=128` | 602 | 614 | 1536 | 25,0 s |
| `reasoning_budget_tokens=128` (sem informar tags) | 332 | 521 | 706 | 13,9 s |
| padrão, `max_tokens=300` (o antigo **Low**) | 300 | 1176 | **0** | 12,6 s (`finish=length`) |

Uma pergunta por condição: é um sinal de ordem de grandeza, não um benchmark. Mas o último caso é decisivo: **o Low atual gasta os 300 tokens pensando e entrega resposta vazia.**

## O que o llama.cpp já oferece

Fonte primária: o código e o README do build local (`tools/server/README.md`, `server-schema.cpp`, `common/sampling.cpp`).

- **Por requisição**
  - `chat_template_kwargs: {"enable_thinking": false}` desliga o raciocínio (o template fecha um bloco `<think></think>` vazio).
  - `reasoning_effort: "none"` também desliga; qualquer outro valor é repassado ao template.
  - `reasoning_budget_tokens: N` impõe um **teto de tokens de raciocínio por amostragem**: ao esgotar, o sampler força `</think>` e o modelo passa a responder. As tags de início e fim são deduzidas do template. É o "budget forcing" do artigo s1, aplicado no decodificador. `reasoning_budget_message` injeta uma frase antes do fechamento.
  - `reasoning_control: true` arma o controle em tempo real: `POST /v1/chat/completions/control` com `action: reasoning_end` encerra o raciocínio **agora**, com o modelo já gerando.
- **Por servidor** (valores padrão): `--reasoning on|off|auto`, `--reasoning-effort`, `--reasoning-budget`, `--reasoning-budget-message`.

Fontes secundárias (a documentação varia por versão, confirmar sempre contra o build em uso):
- [SSD Nodes, reasoning effort local (2026-10-12)](https://www.ssdnodes.com/learn/reasoning-effort-settings-local-llm) descreve o `--reasoning-budget` e os níveis do `--reasoning-effort`.
- [Discussão llama.cpp #23351](https://github.com/ggml-org/llama.cpp/discussions/23351) relata que o `chat_template_kwargs` por requisição foi marcado como obsoleto em algumas versões. No nosso build o README ainda o documenta e o teste acima confirmou que funciona; vale proteger com `reasoning_effort`.
- [s1: Simple test-time scaling](https://arxiv.org/html/2501.19393v2): cortar o raciocínio forçando o delimitador de fim, ou estendê-lo suprimindo o delimitador e anexando "Wait".
- Ollama: [Spring AI PR #4821](https://github.com/spring-projects/spring-ai/pull/4821/files) e [docs OpenClaw](https://docs.openclaw.ai/providers/ollama/advanced.md) indicam `think` booleano para a maioria dos modelos (Qwen3) e `low|medium|high` só para o gpt-oss. Não há orçamento em tokens.

## Opções de desenho

1. **Effort = orçamento de raciocínio (recomendado para llama.cpp).** Cada nível vira `reasoning_budget_tokens`, e `max_tokens` passa a ser orçamento + folga para a resposta, nunca menos.
2. **Effort = chave liga/desliga ou nível.** Para provedores sem orçamento (Ollama, outros): `none`/`low|medium|high` por `reasoning_effort`, ou só ligado/desligado.
3. **Effort adaptativo por etapa.** O custo do raciocínio se repete a cada rodada de ferramenta. A primeira chamada do turno (planejar) recebe o orçamento do nível; as chamadas seguintes (depois de `list_files`, `read_file`, resultado de comando) recebem orçamento curto ou zero, e voltam ao cheio quando há erro de ferramenta.
4. **Interrupção ao vivo.** Uma tecla "parar de pensar" usando `reasoning_control` + `reasoning_end`.
5. **Rodadas separadas do effort.** O limite de rodadas é política do agente (tarefa de vários arquivos precisa de mais), com "continuar" automático ou limite alto com aviso. Deixa de depender do effort.

## Proposta de níveis (a validar com benchmark)

| Nível | Raciocínio | Rodadas seguintes |
|---|---|---|
| Off | desligado | desligado |
| Low | 256 tokens | desligado |
| Medium | 1024 tokens | 256 |
| High | 4096 tokens | 1024 |
| Ultra | sem teto | sem teto |

`max_tokens` = raciocínio + 1024 de resposta. Os números devem ser calibrados no benchmark do M7 (15 tarefas), medindo sucesso e tempo por nível.

## Perguntas em aberto

- Valores acima valem para o Ornith. Outros modelos exigiriam outra calibração.
- Com `reasoning_budget_tokens` o texto cortado pode sair incompleto; a mensagem de fechamento ajuda, mas precisa de medição em tarefas reais.
- O `reasoning_format` precisa continuar em `deepseek` para o raciocínio nunca aparecer na TUI nem ser salvo (regra existente).
