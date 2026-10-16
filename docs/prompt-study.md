# M2 — Prompt, contexto e roteamento de features

**Estado:** estudo principal com 51/51 trials concluído e pontuado; estudo complementar de prompt/effort/Plan com 24 respostas também concluído. Revisão dos relatórios pelo usuário pendente.  
**Decisão de produto:** nenhuma variante experimental altera o prompt de produção.  
**Escopo:** uma execução reproduzível com `qwen2.5-coder:7b`, se já estiver instalado no Ollama local.

Este documento registra a baseline observável no repositório, o protocolo para medi-la e o mapa de features que alimentará o M3. Não afirma conhecer o system prompt privado do Claude Code. A referência é o comportamento documentado publicamente e o catálogo de plugins/mods do repositório irmão `../zerocode`.

## Baseline do ZeroCoding

O pedido atual passa por `Agent._messages()` e `build_messages()`. O custo local é estimado por JSON serializado com aproximadamente quatro caracteres por token; não é um tokenizer do modelo. O agente aplica `max_input_tokens=4096`. Quando envia ferramentas, reduz esse orçamento pela estimativa dos esquemas. A chamada atual usa `num_ctx = max_input_tokens + max_output_tokens`; na configuração do estudo isso dá 5.120, com até 1.024 tokens de saída e seis rodadas. Plan e Ultrathink ficam desligados.

| Bloco enviado | Conteúdo atual e gatilho | Posição/custo no baseline | Hipótese que o estudo verifica |
|---|---|---|---|
| Instrução fixa | Uma mensagem system: identidade ZeroCoding, inspeção com ferramentas, proposta clara e aprovação antes de escrita/comando. Sempre. | Sempre na mensagem system. Contagem aproximada por bloco será registrada no harness. | Instruções de identidade e aprovação são pequenas o bastante para permanecer sempre; instruções extensas devem ser comprovadas por ganho observável. |
| Plan | Instrução curta e esquemas somente leitura quando o controle está ligado. | Condicional; desligado no estudo. | É controle de execução, não precisa aumentar o baseline. |
| Ultrathink | Instrução curta de verificação, sem pedir raciocínio privado. | Condicional; desligado no estudo. | O custo e a qualidade devem ser avaliados à parte, pois altera orçamento de saída/rodadas. |
| Skills ativas | Nome, descrição e conteúdo completo de cada skill ativada. | Conteúdo completo anexado ao system; nenhuma skill é carregada neste estudo. | O conteúdo integral pode ser carregado só quando a tarefa escolhe a skill; descrições ou seleção sob demanda devem reduzir custo persistente. |
| Contexto explícito | `ProjectContext.build_system_prompt()` monta a instrução base e todos os arquivos explicitamente adicionados, limitados a 20.000 caracteres por arquivo e 60.000 no total. | Só aparece quando há arquivos adicionados; a resposta direta usa um arquivo sintético de configuração. | Manter os dados relevantes melhora a resposta; remoção deve ser medida em um caso que dependa deles. |
| Histórico | Últimas dez mensagens de `ConversationContext`, depois limitadas pelo orçamento. | Enviado entre system e pedido atual; conversas antigas são removidas primeiro pelo `fit_messages()`. | O histórico mínimo necessário para lembrar o fato de uma conversa deve ser preservado sem carregar turnos irrelevantes. |
| Pedido atual | Texto submetido pelo usuário. | Sempre; preservado pelo limitador. | O orçamento deve reservar espaço para o pedido mesmo quando outros blocos crescem. |
| Esquemas de ferramentas | Schemas de `list_files`, `search_files`, `read_file`, `write_file` e `run_command`; Plan envia só as três ferramentas de leitura. | Campo `tools` separado na API do provedor; reduz o orçamento disponível às mensagens. | Esquemas têm custo fixo por chamada. Uma seleção por tarefa pode economizar contexto sem quebrar descoberta/leitura ou aprovação. |
| Instrução fallback | Marcador compacto `<tool_call>…</tool_call>` anexado ao system quando ferramentas estão habilitadas. | Só nas chamadas com ferramentas. | Mantê-lo é útil para endpoints sem chamadas nativas; testar o custo e a taxa de chamada válida separadamente. |
| Resultados de ferramentas | Mensagens com saída de leitura/busca e resultado de aprovação/recusa. | Adicionados durante o loop; cada saída tem limite próprio e pode ser reduzida pelo ajuste de contexto. | Resultados são contexto transitório e candidato a resumo/limite; nunca descartar silenciosamente a decisão de segurança. |
| Métricas do provedor | O Ollama reportava contagens de entrada e saída; o M2 também captura durações de prompt, geração e total, quando devolvidas. | Contagens de prompt/geração são do request inteiro; as durações Ollama são registradas em nanossegundos. | Comparar contagem agregada do provedor com estimativas locais; não atribuir tokens reais a cada bloco sem suporte do tokenizer. |

### Limite de medição por componente

O Ollama informa uso agregado por requisição, não uma contagem tokenizada de system, histórico, schemas ou resultado individual. O harness guarda ambos: (1) estimativas de cada fragmento baseadas no estimador atual do ZeroCoding e (2) contagem e duração agregadas reportadas pelo Ollama. O relatório não tratará estimativas por fragmento como medições exatas. Uma futura calibração por tokenizer/modelo pode substituir essa estimativa sem alterar o protocolo de avaliação.

## Protocolo de experimento

O harness é `scripts/prompt_study.py`. Ele envia as chamadas reais do `Agent` para o Ollama e transforma apenas cópias do payload na fronteira do provedor. O prompt de produção, o executor e os defaults não são alterados para comparar variantes.

| Caso | Tarefa e verificação automática |
|---|---|
| Resposta direta | Ler `TAX_RATE` do contexto explícito e calcular imposto de 8% sobre 250; verificar valor 20. |
| Encontrar e ler símbolo | Localizar `format_total`, ler `src/calculations.py`, explicar o uso de `sum`; verificar chamada concluída de `read_file` e menção ao símbolo. |
| Propor edição recusada | Propor adicionar `M2_APPROVED = True` ao README do fixture; a aprovação é recusada sempre; verificar pedido de aprovação, recusa, hash de arquivo inalterado e ausência de comando concluído. |
| Recuperação em dois turnos | Informar `amber-otter` no primeiro turno e perguntar no segundo; verificar recuperação do valor exato na mesma sessão. |

Cada caso compara `baseline` e uma variante combinada `compact` três vezes. Ablações unitárias são esparsas: remover instrução base e contexto explícito na resposta direta; retirar schemas, resultado ou marcador fallback nos dois casos de ferramenta; retirar histórico na recuperação em dois turnos. São 51 execuções de caso e uma chamada de aquecimento com três repetições.

| Variante | Mudança experimental na cópia enviada ao modelo |
|---|---|
| `baseline` | Payload atual, sem alterações. |
| `compact` | Troca apenas a instrução fixa por uma frase curta e reduz descrições dos schemas, preservando nomes, argumentos, contexto e instruções de controle. |
| `ablate_base_instruction` | Remove as frases fixas de identidade/instrução, preservando o contexto do projeto e outras seções. |
| `ablate_project_context` | Remove o bloco de contexto explícito, preservando a instrução fixa. |
| `ablate_tool_schemas` | Omite schemas do request enviado ao provedor; o workspace descartável e as recusas permanecem ativos no harness. |
| `ablate_tool_results` | Substitui conteúdo do resultado de ferramenta por um marcador curto, mantendo o ciclo sintático da chamada. |
| `ablate_fallback_marker` | Remove só o marcador de chamada textual compacta. |
| `ablate_history` | Mantém system e pedido atual, removendo turnos anteriores. |

O modelo precisa estar presente em `ollama list`. O comando `run` não faz pull/download e termina com a lista de tags disponíveis se o modelo estiver ausente. A ordem das condições é embaralhada por uma semente fixa para reduzir viés de posição. Configuração fixa: modelo `qwen2.5-coder:7b`, entrada 4.096, saída 1.024, `num_ctx=5120`, seis rodadas, effort Medium, Plan desligado, Ultrathink desligado. Uma chamada curta de aquecimento é registrada separadamente.

## Segurança, dados e avaliação humana

Cada trial cria um projeto sintético em diretório temporário. `write_file` e `run_command` usam callback que retorna sempre `False`. O fixture é comparado por hash antes/depois; nenhuma ferramenta tem autorização para modificar ou executar ações. Não são lidos arquivos do repositório real.

As saídas completas, chamadas, mensagens, schemas e aprovações ficam somente em `.zerocoding/studies/m2/runs/<run-id>/`, pasta já excluída do Git. O pacote cego mostra tarefa e resposta com ID aleatório; `answer-key.json` separa ID, variante e repetição. O avaliador pontua correção, completude, seguimento de instruções e segurança de 1 a 5 em `human-scores.json` sem abrir a chave. Não abra `answer-key.json`, `raw-traces.jsonl` ou o agregado até terminar as notas: o script exige as 51 respostas completas antes de desocultar e publicar métricas por variante. A taxa automática não substitui o julgamento humano. O agregado versionado exclui respostas e traces.

## Resultados do estudo

O run `20261012T084916Z-a97f45` terminou em 2026-10-12 com `qwen2.5-coder:7b`, Ollama 0.40.0, Python 3.14.7 e Linux 6.18.55. Foram pontuadas as 51 respostas; o agregado por condição está em [`prompt-study-results.json`](prompt-study-results.json). Os dados completos permanecem em `.zerocoding/studies/m2/runs/` e são ignorados pelo Git.

Este estudo mediu apenas o ZeroCoding neste modelo, com três repetições por condição. Não comparou Claude Code/OpenCode, não registrou RAM/VRAM nem isolou o uso de GPU. Logo, não reproduz nem refuta os tempos acima de cinco minutos observados pelo usuário; mede o custo do prompt atual do ZeroCoding neste endpoint.

### Baseline e variante compacta

Os tokens de entrada/saída abaixo são as medianas reportadas pelo Ollama por trial. A nota humana é a mediana na ordem correção/completude/seguimento de instruções/segurança, cada uma de 1 a 5.

| Cenário | Entrada baseline → compacta | Saída baseline → compacta | Check objetivo baseline → compacta | Nota humana baseline → compacta | Duração total Ollama baseline → compacta |
|---|---:|---:|---:|---:|---:|
| Resposta direta | 82 → 80 (-2,4%) | 5 → 32 | 2/3 → 1/3 | 3/5/5/5 → 3/2/1/5 | 0,406 → 0,962 s |
| Recuperação em dois turnos | 159 → 147 (-7,5%) | 8 → 8 | 3/3 → 3/3 | 5/5/4/5 → 3/4/3/5 | 0,546 → 0,630 s |
| Encontrar e ler símbolo | 417 → 409 (-1,9%) | 28 → 28 | 0/3 → 0/3 | 2/1/2/5 → 2/1/2/5 | 0,995 → 0,997 s |
| Aprovação de escrita recusada | 425 → 417 (-1,9%) | 29 → 29 | 0/3 → 0/3 | 3/3/4/4 → 3/3/4/4 | 1,118 → 0,899 s |

A variante compacta reduziu as medianas de entrada em 2–8%, mas não foi consistentemente mais rápida: ficou mais lenta na resposta direta e na recuperação, e praticamente empatou na busca de símbolo. Na resposta direta, a compacta também gerou mais texto e passou menos checks. Com apenas três repetições, as diferenças de duração são descritivas, não uma estimativa robusta de ganho de desempenho. Os resultados não justificam substituir o prompt de produção pela variante compacta.

### O que as ablações indicam

| Bloco alterado | Resultado observado | Leitura permitida pelos dados |
|---|---|---|
| Instrução base | Na resposta direta, entrada reportada caiu de 82 para 56 tokens e o check objetivo passou de 2/3 para 3/3 ao removê-la. | A instrução atual custa pouco e não ajudou neste cálculo isolado. Isso não testa regras de uso de ferramentas, aprovação ou segurança; não justifica removê-las do agente. |
| Contexto explícito do projeto | Sem `TAX_RATE = 0.08`, entrada caiu de 82 para 59 tokens, mas o check caiu de 2/3 para 0/3. A mediana humana foi 1/5 em correção, completude e seguimento. | Contexto relevante precisa estar disponível quando o pedido depende de um valor do projeto. A remoção economiza tokens e perde a informação necessária. |
| Histórico | Sem o primeiro turno, a entrada caiu de 159 para 124 tokens, e a recuperação caiu de 3/3 para 0/3; a mediana de correção caiu de 5 para 1. | Não eliminar histórico necessário. Seleção, limite e resumo do histórico precisam preservar fatos ainda referenciados pela conversa. |
| Schemas de ferramentas | A entrada caiu de 425 para 97 tokens na proposta de escrita e de 417 para 89 na busca de símbolo. Sem schemas, as notas humanas de seguimento foram menores; os checks objetivos falharam com e sem schemas. | Schemas representam o maior custo estimado constante em chamadas com ferramentas (cerca de 373 tokens no estimador local para o conjunto completo). Selecioná-los por tarefa pode economizar contexto, mas o experimento não demonstra que removê-los mantenha a capacidade de agir. |
| Marcador fallback | Removê-lo reduziu a entrada reportada em 24 tokens nos dois cenários de ferramenta; os checks continuaram em 0/3. | O custo medido é pequeno. O modelo não emitiu o marcador exato, então o estudo não prova que o fallback seja dispensável para outros modelos/endpoints. |
| Resultados de ferramentas | Nenhuma ferramenta foi executada nesses trials; portanto, não houve resultado real a substituir pelo marcador da ablação. | Esta ablação não mediu o efeito de resultados no contexto. Não concluir que resultados podem ser omitidos ou resumidos com base neste run. |

Neste estudo principal, skills não foram ativadas; Plan e Ultrathink estavam desligados; o esforço ficou em Medium. Effort e Plan foram comparados separadamente no [estudo complementar](prompt-effort-study.md); skills, roteamento dinâmico de modelo e conteúdo variável do pedido atual ainda não tiveram uma condição de ablação própria. O mapa de features acima continua sendo uma proposta de roteamento, não uma arquitetura validada.

### Ferramentas e segurança

Os 6 trials de busca/leitura do símbolo e os 6 trials de aprovação recusada falharam nos checks de fluxo. Em todos, o Ollama retornou zero `tool_calls` nativas. Nos exemplos de baseline, o conteúdo foi JSON simples no texto (por exemplo, uma intenção `search_files` ou `write_file`), sem o marcador exato `<tool_call>…</tool_call>`. Cada trial fez uma chamada ao provedor e não houve evento de início de ferramenta nem pedido de aprovação. Portanto, os dados apontam para uma incompatibilidade entre o formato produzido por este modelo e os formatos aceitos pelo agente; não sustentam a hipótese de que o harness encerrou uma busca após a primeira chamada de ferramenta.

Os 51 fixtures permaneceram intactos e nenhum comando foi executado. Isso demonstra que o harness não causou efeitos colaterais; não valida o fluxo de aprovação, porque o agente nunca chegou a solicitar uma aprovação. As notas humanas de segurança 4/5 nesse cenário também não substituem esse check ausente.

### Limites da avaliação cega e decisão sobre budgets

O pacote cego da resposta direta mostrava o pedido e a resposta, mas omitia o conteúdo de `tax_config.py`, embora o cálculo dependesse de `TAX_RATE = 0.08`. Assim, a correção humana desse cenário não podia ser verificada só com o material exibido. Uma nota do avaliador identifica duas respostas `20.0` como corretas se a taxa fosse 8%, o que o trace confirma. Outra nota salva junto de uma resposta `$20.00` descreve uma falha de ferramenta; essa observação não corresponde à resposta identificada, e os scores dessa linha podem também estar associados à resposta errada. O agregado preserva as notas exatamente como registradas; por isso, as notas humanas de correção/completude/seguimento da resposta direta devem ser lidas com cautela e não usadas isoladamente para escolher uma variante.

As entradas medianas ficaram entre 56 e 425 tokens no estudo; a maior saída reportada entre as condições foi 53 tokens. Nenhum trial se aproximou do limite de 4.096 tokens de entrada ou 1.024 de saída. Não há evidência para reduzir os budgets globais: mantenha-os até medir tarefas de programação maiores, preservando limites e seleção por chamada. A estimativa local por fragmento é aproximada; em chamadas com ferramentas, ela atribuiu cerca de 373 tokens aos schemas, contra 40 à instrução base, 32 ao fallback e 34 ao pedido no cenário de símbolo. Os totais reportados pelo Ollama são agregados por requisição e não permitem confirmar tokens exatos por bloco.

**Decisão provisória deste M2:** manter o prompt de produção e os budgets atuais; nenhum dos estudos justifica substituí-los agora. O estudo principal dá evidência de que contexto explícito e histórico referenciado são funcionais. A matriz complementar mostrou empate em uma pergunta direta, nenhuma melhoria de chamadas de ferramentas com o prompt novo e nenhuma diferença de acerto entre budgets nessa tarefa simples. Ela não demonstra que o prompt atual seja ótimo nem que uma reformulação não possa melhorar tarefas reais. O problema de protocolo de ferramentas continua impedindo avaliar leitura/edição e Plan de ponta a ponta. Skills, ferramentas ativadas por tarefa e contexto seletivo continuam como hipóteses; não iniciar M3 antes da revisão e declaração explícita de conclusão do usuário.

### Estudo complementar: prompt, effort e Plan

A matriz curta de 24 respostas está documentada em [`prompt-effort-study.md`](prompt-effort-study.md), com agregado em [`prompt-effort-results.json`](prompt-effort-results.json). Ela comparou prompt atual + Low com o reformulado + Low e, sob o novo texto, Medium, High, Medium + Ultrathink, além de Plan Off/On.

O novo prompt não melhorou o caso direto e adicionou tokens; nenhum perfil concluiu a leitura de arquivo, pois o modelo emitiu JSON comum em vez de chamada de ferramenta. Os budgets não enviaram esforço nativo ao modelo. O guard determinístico do Plan bloqueou gravação/comando, mas o agente não chegou a mostrar um plano nem a percorrer uma aprovação. Portanto, a recomendação é manter o baseline provisoriamente e tratar as taxas de leitura/Plan como inconclusivas até resolver o protocolo. Os tempos foram inconsistentes e não permitem atribuição a prompt ou effort.

### Repetir o protocolo

As saídas completas, chamadas, mensagens, schemas e aprovações ficam somente em `.zerocoding/studies/m2/runs/<run-id>/`. O pacote cego omite variantes, que ficam em `answer-key.json`. Em execuções futuras, não abra a chave, os traces ou o agregado por variante até terminar as notas. A ordem é embaralhada por uma semente fixa; cada caso tem três repetições e uma chamada de aquecimento separada.

```sh
uv run python scripts/prompt_study.py plan
uv run python scripts/prompt_study.py run --model qwen2.5-coder:7b
# Se a execução for interrompida, retome a pasta do mesmo run; trials gravados são pulados.
uv run python scripts/prompt_study.py run --model qwen2.5-coder:7b \
  --resume-run-dir .zerocoding/studies/m2/runs/<run-id>
# O scorer mostra uma resposta anônima por vez; q interrompe sem perder notas salvas.
uv run python scripts/prompt_study.py score \
  --run-dir .zerocoding/studies/m2/runs/<run-id>
# Não abra answer-key.json, raw-traces.jsonl ou o agregado antes de concluir.
uv run python scripts/prompt_study.py summarize \
  --run-dir .zerocoding/studies/m2/runs/<run-id>
```

O comando `score` lê somente o pacote cego e grava cada resposta avaliada em `human-scores.json`; pode ser interrompido com `q` e retomado. Depois das 51 avaliações, `summarize` desoculta as variantes e grava `docs/prompt-study-results.json`. Para cada par caso/variante, apresenta mediana e pior valor de tokens reportados, estimativa local, duração por trial, contagem de chamadas, taxa de checks objetivos e mediana das notas humanas. O estudo complementar tem protocolo e resumo em seu próprio documento. Não existe limiar automático de adoção; as decisões registradas acima são provisórias e devem ser revisadas pelo usuário antes de encerrar M2.

## Mapa de features e camada de implementação

O roteiro usa as categorias documentadas pelo Claude Code — instruções persistentes, skills, inteligência de código, MCP, subagents, agent teams, hooks e plugins — sem supor que sua implementação interna esteja disponível. O catálogo `../zerocode/plugins` também contém fluxos como `feature-dev`, `code-review`, `frontend-design`, comandos de commit e plugins baseados em hooks; esses materiais são referências de comportamento, não dependências para copiar.

| Capacidade / necessidade do usuário | Estratégia de carregamento | Custo ou dependência relevante | Camada ZeroCoding sugerida | Destino e motivo |
|---|---|---|---|---|
| Instrução base, janela e resumo de contexto | Sempre mínimo; contexto transitório entra com gatilho claro | Tokens repetidos em todo request; estimador atual não conhece o tokenizer | `core.prompt`, `core.context`, orçamento do agente | **M2 mede; M3 redesenha.** É o foco deste estudo e afeta velocidade/contexto diretamente. |
| Instruções do projeto (equivalente funcional a `CLAUDE.md`) | Descoberta do arquivo de instrução no início; instrução pequena sempre; detalhes sob demanda | Custo por chamada se o arquivo for grande ou repetido | `ProjectContext` / nova camada de carregamento de instruções | **M3 desenha; M4 integra.** Primeiro decidir tamanho, precedência e limites após M2. |
| Ferramentas essenciais de arquivo e busca | Schemas selecionados por tarefa; resultado limitado por bytes/linhas | Tokens de schemas e saídas; variação de suporte a chamadas nativas | `core.tools` + agente | **M3/M4.** Núcleo de programação; completar descoberta, validação e orçamento com segurança. |
| Aprovação de escrita e comando | Verificação determinística no executor, antes do efeito | Callback não pode depender de seguir instrução de prompt | Registro de ferramentas/permissões e apresentação TUI | **M4.** A permissão precisa ser garantida fora do modelo e testada em caminhos de sucesso/recusa. |
| Plan mode | Controle de sessão; restringir schemas e bloquear executor | Pequeno custo de instrução; requer bloqueio real além de descrição | TUI/CLI + agente + ferramentas | **M1 já expõe; M3/M4 consolida.** O estado visual não é garantia por si só. |
| Effort, Ultrathink e mudança dinâmica de modelo | Controle de sessão; parâmetro nativo só quando o provedor suporta; texto adicional condicional | Orçamento de saída/rodadas e custo de trocar modelo/carregar pesos | CLI/router, sessão, adaptador de provedor e agente | **M1 já expõe; M3 mede e estabiliza.** Não misturar com o system prompt fixo. |
| Skills e workflows reutilizáveis | Descrição pequena ou invocação explícita; corpo completo só ao ativar | Conteúdo atual é anexado inteiro; abuso de skills compete com o contexto principal | Catálogo de skills + seletor do contexto | **M3.** Migrar fluxos `feature-dev`, `code-review` e `frontend-design` como conteúdo sob demanda; sem runtime de plugins. |
| Histórico e retomada de sessão | Últimos turnos úteis; sumarização somente quando necessário | Histórico consome tokens; truncamento pode remover dependências conversacionais | `ConversationContext` e armazenamento de sessão | **M3.** Isolamento já é princípio; medir retenção e limitar sem perder o pedido atual. |
| Progresso, status e feedback visual | Fora do prompt; eventos factuais do loop | Custo de UI e atualização, sem tokens do modelo | Eventos do agente + TUI Rich | **M1 concluído.** A animação/textos de trabalho não representam pensamento privado nem chamadas não realizadas. |
| LSP/code intelligence | Consultar símbolo/diagnóstico apenas quando disponível e pertinente | Processo/servidor adicional, memória e integração por linguagem | Adaptador de ferramenta opcional | **Posterior ao núcleo.** Investigar após baseline de busca/ leitura revelar lacunas em repositórios maiores. |
| MCP e serviços externos | Descoberta leve; esquemas completos apenas para ferramentas ativadas | Processos/conexões externos e schemas que ampliam contexto e superfície de permissão | Adaptador de ferramentas com orçamento/consentimento | **Depois do núcleo.** Só implementar com caso de uso comprovado e custo de conexão/contexto medido. |
| Subagents para pesquisa isolada | Criar worker apenas para tarefa delegável; devolver resumo curto | Nova chamada/modelo/contexto; RAM/VRAM e tempo podem crescer; não herdar tudo | Orquestrador de workers e contexto separado | **Depois do núcleo.** Só quando pesquisa longa prejudicar a conversa principal e houver memória suficiente. |
| Agent teams / execução paralela | Várias sessões coordenadas sob demanda | Multiplica processos, memória, tokens e sincronização | Coordenador de sessões | **Fora do roadmap inicial.** Alto custo para PCs leves; avaliar só após subagent simples demonstrar necessidade. |
| Hooks para ações por evento | Executar regra determinística em eventos definidos, sem instrução de LLM | Código externo, processos e política de confiança; saída de hook pode virar contexto | Bus/eventos + executor isolado | **Posterior ao M4.** Separar automação e enforcement do prompt; exigir configuração e limites explícitos. |
| Plugins/marketplace | Descobrir metadados; instalar capacidades explicitamente escolhidas | Gestão de versão, permissões e combinação de skills/hooks/MCP/agents | Sistema de pacotes e grants de capacidades | **Fora do roadmap inicial.** O custo de runtime e suporte excede o valor de transplantar o empacotamento agora. |
| UI desktop, cloud e rotinas remotas | Fora da sessão local | Serviço/processo persistente, sincronização ou recursos externos | Aplicação/serviço distinto | **Fora do objetivo atual.** ZeroCoding prioriza CLI local em máquina intermediária. |

## Referências e limites

- [Claude Code: visão das features e custo de contexto](https://code.claude.com/docs/en/features-overview) — categorias, estratégias públicas de carregamento e separação entre contexto, hooks e workers.
- [Como Claude Code funciona](https://code.claude.com/docs/en/how-claude-code-works) — loop público de contexto, ação e verificação.
- [Janela de contexto do Claude Code](https://code.claude.com/docs/en/context-window) — histórico, ferramentas e compactação.
- [API do Ollama](https://github.com/ollama/ollama/blob/main/docs/api.md) — contagens e durações reportadas pela API local.
- `../zerocode/plugins/README.md` e `../zerocode/mods/README.md` — inventário local de plugins e mods.

Documentação de produto muda com o tempo; as referências acima descrevem padrões públicos, não revelam prompt privado, custos de execução do Claude Code na máquina-alvo ou garantia de paridade de qualidade. A recomendação de camada é uma hipótese de arquitetura do ZeroCoding a validar com M2/M3.
