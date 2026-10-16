# Avaliação de modelos locais

## Resultados medidos (M5)

**Estado:** medido em 2026-10-16 para o **único modelo de trabalho do projeto (Ornith-1.5-9B Q5_K_M)**. Os modelos da matriz abaixo (Qwen3-8B, Qwen3.5-9B, Gemma 4 12B, Qwen2.5-Coder-7B) **não foram reavaliados**: `context.md` mantém o Ornith como modelo único nesta etapa e esses modelos eram servidos via Ollama, hoje legado. O harness é independente de modelo (`--label`), então a comparação roda sem mudar código quando `context.md` permitir.

**Reproduzir:** subir o `llama-server` (comando no README) e rodar `uv run python scripts/m5_eval.py --label <id> --repetitions 3`. Os dados completos por tentativa ficam em `docs/m5-ornith-1.5-9b-q5_k_m-results.json`.

### Configuração

| Item | Valor |
|---|---|
| Máquina | Ryzen 5 4600G, 16 GB RAM, RX 5700 8 GB (Vulkan0) |
| Modelo | Ornith-1.5-9B, GGUF Q5_K_M (`/mnt/jogos/huggingFaceModels/Ornith-1.5-9B-Q5_K_M.gguf`) |
| Servidor | llama.cpp `b11681-5e03a1ff4`, `-ngl 99 -c 8192 -t 6`, 4 slots automáticas (sem `-np 1`) |
| ZeroCoding | `max_input_tokens` 4096, `max_output_tokens` 1024, 6 rodadas (Medium), `dynamic_context` desligado, contador de tokens via `/tokenize` |
| Amostragem | a configurada no servidor; o harness não altera temperatura/top-p |
| Repetições | 3 por caso, workspace temporário novo a cada tentativa, aprovação programática |

### Conclusão das tarefas e validade das chamadas

**21/21 tentativas concluíram a tarefa**, verificadas por checagem objetiva (conteúdo do arquivo, existência de arquivo, aprovações pedidas, resultado do comando). Houve **35 chamadas de ferramenta, 2 com erro (5,7%)**, ambas no caso `plan_blocks_write`; todas as demais foram válidas. A causa dos 2 erros não foi investigada (o harness só guarda a contagem); a hipótese provável é leitura de um arquivo inexistente, o que seria erro legítimo e não de formato. Nenhuma escrita ou comando recusado/bloqueado foi executado.

| Caso | Concluídos | Duração (mediana / pior) | Tokens de entrada (med / pior) | Tokens de saída (med / pior) |
|---|---|---|---|---|
| `direct` (sem ferramenta) | 3/3 | 4,1 s / 4,3 s | 771 / 771 | 83 / 86 |
| `read` (ler e explicar) | 3/3 | 12,4 s / 13,1 s | 1 646 / 2 551 | 257 / 264 |
| `search` (buscar símbolo) | 3/3 | 8,7 s / 10,6 s | 1 656 / 1 656 | 173 / 215 |
| `edit_approved` (editar, aprovado) | 3/3 | 13,5 s / 16,1 s | 3 739 / 4 846 | 269 / 317 |
| `write_refused` (escrita recusada) | 3/3 | 8,3 s / 9,2 s | 1 639 / 1 641 | 169 / 187 |
| `plan_blocks_write` (Plan bloqueia) | 3/3 | 26,4 s / 28,8 s | 1 193 / 1 852 | 570 / 609 |
| `command_approved` (rodar testes) | 3/3 | 14,7 s / 15,0 s | 3 900 / 3 913 | 262 / 271 |

Tokens de entrada/saída são a soma do `usage` do servidor em todas as chamadas do turno (um turno com ferramenta faz várias chamadas).

### Velocidade e memória

| Métrica | Resultado |
|---|---|
| Geração | **≈22 tokens/s** (mediana por caso 21,9–22,2; pior 21,5), estável entre casos |
| Processamento do prompt (1ª chamada) | 327–362 ms nas medianas dos casos com ferramenta; 143 ms no Plan |
| RAM (RSS do `llama-server`) | 4,9 GB ocioso, pico 5,0 GB |
| VRAM (GPU inteira, `mem_info_vram_used`) | 7,6 GB ocioso com o modelo carregado, pico 7,6 GB (de 8,57 GB) |

Limitações dessas medidas:

- **Não há medida de tempo até o primeiro token real:** o provider não faz streaming. `first_prompt_ms` é o `prompt_ms` do llama.cpp na primeira chamada e **inclui efeito do cache de prompt** (o prefixo repetido entre tentativas não é reprocessado), então não representa a velocidade de prefill do zero. As medições antigas de `context.md` (112–123 tokens/s de prompt) são de prompt frio e não são comparáveis.
- **A VRAM é da GPU inteira**, não só do processo; o consumo do desktop entra na conta. Como já estava em 7,6 GB antes de qualquer pedido, o pico mostra apenas que o contexto de 8K não estourou os 8,57 GB.
- **A geração subiu para ~22 tokens/s** contra 17,8–18,9 registrados antes em requests curtas; o build do servidor mudou (`b11429` → `b11681`). Não isolei a causa.
- Três repetições por caso dão pouca potência estatística; leia mediana e pior caso como ordem de grandeza.
- Uma tarefa por caso, prompts curtos, projeto minúsculo: não mede qualidade em código real nem tarefas longas. O maior total de tokens de entrada em um caso (somando as chamadas do turno) foi 4 846; o orçamento de 4096 vale por chamada e não foi medido sob pressão.

### O que cada caso do M2/M4 cobre

Os casos 1–4 e 7 do roteiro "Casos por modelo" abaixo estão no harness (resposta direta, localizar/ler, editar com diff aceito, escrita recusada, comando aprovado) mais o bloqueio do Plan. Os demais são determinísticos e independem do modelo, então ficam em testes automatizados (`tests/test_m4_workflow.py`): comando negado sem processo iniciado, isolamento de sessão, corte de prompt maior que o limite (`tests/test_tokens.py`, `tests/test_agent_tools.py`), argumentos inválidos, ferramenta inexistente e limite de rodadas.

### Recomendação para a máquina-alvo

Para o Ryzen 5 4600G + RX 5700 8 GB, **Ornith-1.5-9B Q5_K_M com Vulkan e contexto de 8192 é uma configuração utilizável**: conclui o ciclo de leitura, busca, edição e comando sem erro de formato de chamada, em 4–30 s por turno, a ~22 tokens/s, usando ~89% da VRAM. A margem de VRAM é pequena (~1 GB): contexto maior ou outra aplicação usando a GPU pode forçar offload. O README recomenda `-np 1`; este servidor rodou com 4 slots automáticas e o efeito disso na memória não foi medido. Não há dados para recomendar outro modelo nesta máquina; a comparação com os candidatos abaixo continua pendente e só deve ocorrer após atualização do `context.md`.

---

## Matriz de comparação pendente (histórica, baseada em Ollama)

Esta seção define a matriz reproduzível original para validar chamadas de ferramenta e latência em PCs leves. Ela **ainda não foi executada** para esses modelos: eles precisam estar instalados e servidos (o roteiro foi escrito para Ollama, hoje legado; o harness `scripts/m5_eval.py` fala com qualquer `llama-server`).

## Matriz inicial

| Grupo | Modelos Ollama | O que comparar |
|---|---|---|
| Qwen coder | `qwen2.5-coder:3b`, `qwen2.5-coder:7b` | escolha de ferramenta, argumentos e edição de código |
| Qwen geral | `qwen3:4b`, `qwen3:8b` | uso de ferramentas com raciocínio e latência |
| Gemma | `gemma4:e2b`, `gemma4:e4b` | chamada nativa e aderência aos esquemas |
| Phi | `phi4-mini` | comparação de modelo compacto geral |
| Llama | `llama3.1:8b` | referência compacta de uso geral |

Confirme os nomes/tags disponíveis no host com `ollama list`; os tags mudam conforme a publicação dos modelos.

## Casos por modelo

1. Resposta direta sem ferramenta.
2. Localizar um símbolo e ler o arquivo correto.
3. Propor uma edição e aceitar o diff.
4. Propor uma edição e negar o diff; confirmar que o arquivo não mudou.
5. Pedir um comando, negar a execução e confirmar que nenhum processo foi iniciado.
6. Sessão nova e sessão retomada; confirmar que o histórico de outra sessão não aparece.
7. Prompt maior que o limite; confirmar que turnos antigos são descartados e a pergunta atual permanece.
8. Argumentos inválidos, ferramenta inexistente e limite de rodadas.

## Métricas

Registre por caso: resultado esperado, chamada e argumentos da ferramenta, tokens de entrada/saída reportados pelo Ollama, tempo até o primeiro token, tempo total, tokens por segundo, pico de RAM e VRAM e se a confirmação foi respeitada. Repita cada caso três vezes e reporte mediana e pior caso. Teste no Ryzen 5 4600G, 16 GB RAM e RX 5700, mantendo os mesmos arquivos de projeto, `num_ctx=5120` e versões do Ollama.

O agente usa atualmente uma estimativa de tokens baseada em caracteres para limitar o prompt. Os contadores de tokens retornados pelo Ollama devem ser usados na avaliação para calibrar essa margem por modelo e tokenizer.

## Compatibilidade de chamada

ZeroCoding envia esquemas de ferramenta no formato nativo da API do Ollama/OpenAI-compatible e consome chamadas estruturadas. Se o endpoint responder em texto, é aceito somente o marcador compacto `<tool_call>{"name":"...","arguments":{...}}</tool_call>`. O marcador ainda depende de cada modelo seguir o formato; registre separadamente a taxa de chamada válida e não habilite execução sem aprovação do usuário.
