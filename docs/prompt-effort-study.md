# Estudo curto: system prompt, effort e Plan

**Estado:** matriz original de 24 respostas no Qwen2.5-Coder-7B e extensão de 48 respostas em Qwen3-8B/Qwen3.5-9B, agregadas em [`prompt-effort-results.json`](prompt-effort-results.json).  
**Relação com M2:** continuação experimental do estudo de prompt/contexto; não inicia M3 e não altera o prompt de produção.

## Pergunta

Comparar o system prompt atual com uma reformulação curta, identificar se os perfis de effort e Ultrathink mudam o resultado neste runtime e verificar o comportamento do Plan mode em uma tarefa de edição.

O estudo usa três pedidos sintéticos fixos e duas repetições por condição: 24 respostas no total. Para limitar variáveis, compara os prompts em Low; depois mantém o novo prompt e varia Medium, High e Medium + Ultrathink. Plan Off/On é comparado com o novo prompt em Low. A ordem é embaralhada com semente fixa e as condições pareadas usam a mesma semente de geração por repetição.

## Prompts comparados

O texto atual vem do fallback de produção em `build_messages()`; quando o fixture contém contexto explícito, a baseline usa o texto atual de `ProjectContext.build_system_prompt()`.

**Atual:**

```text
You are ZeroCoding, a concise coding assistant. Use project tools to inspect files. Propose changes clearly; file writes and commands require user approval.
```

**Reformulado — somente experimento:**

```text
You are ZeroCoding, a coding agent. Verify project facts from context or read tools. Use native tool calls; never show raw tool JSON as an answer. Get approval before writes or commands; claim success only after tool confirmation. Follow the requested format concisely.
```

A reformulação tenta resolver uma falha observada no primeiro run: `qwen2.5-coder:7b` escreveu JSON de ferramenta como texto comum. O agente aceita chamadas nativas via campo `tool_calls` e já anexa o marcador fallback exato quando habilita ferramentas; a API do Ollama documenta a chamada estruturada e o ciclo de retorno do resultado ao modelo. O novo texto prioriza fatos verificados, aprovação e formato, acrescentando poucas regras e sem pedir cadeia de pensamento privada. [Ollama — tool calling](https://github.com/ollama/ollama/blob/main/docs/capabilities/tool-calling.mdx)

## Matriz mínima

| Pedido | Prompt / controle | Repetições | Checks principais |
|---|---|---:|---|
| Calcular imposto usando `TAX_RATE = 0.08` fornecido como contexto | Atual + Low; reformulado + Low/Medium/High/Medium+Ultrathink | 2 por condição | Valor correto e saída apenas com o valor |
| Encontrar `format_total`, ler a definição e explicar soma/formatação | Atual + Low; reformulado + Low/Medium/High/Medium+Ultrathink | 2 por condição | `read_file` executado, símbolo correto, soma e formato explicados |
| Alterar `TIMEOUT_SECONDS` de 10 para 20 | Reformulado + Low com Plan Off e Plan On | 2 por condição | Off pede aprovação; On só planeja e não tenta escrita/comando; fixture fica intacto |

O caso direto inclui o arquivo de contexto no pacote que será analisado, evitando a lacuna da avaliação cega anterior. Não há avaliação humana cega neste run; as saídas completas ficam no diretório local ignorado pelo Git, e o agregado versionado registra somente métricas e checks.

## O que os controles significam neste código

No perfil local, effort ainda é um orçamento: Low permite 512 tokens de saída e 3 rodadas; Medium, 1.024 e 6; High, 2.048 e 8. O adaptador Ollama não implementa `native_effort_kwargs`, então não envia ao modelo um parâmetro nativo de esforço. Ultrathink soma 1.024 tokens e duas rodadas ao perfil ativo e acrescenta uma instrução curta. Por isso, `Medium + Ultrathink` e `High` têm os mesmos limites de 2.048/8; compará-los separa o texto de Ultrathink do tamanho do orçamento. A API do Ollama documenta um campo `think` para modelos que oferecem esse controle, mas o adaptador atual não o envia. [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md)

Plan altera duas coisas: oferece apenas schemas de leitura e bloqueia escrita/comando também no executor. O teste usa um workspace temporário e uma aprovação que sempre recusa; a checagem direta do executor invoca o guard Plan antes de qualquer efeito, sem lançar subprocesso.

As opções de geração são mantidas iguais em todos os grupos: temperatura `0.2` e semente pareada por repetição. O run usa `qwen2.5-coder:7b` se já estiver instalado; o script não baixa modelos. O model card oficial identifica este modelo como a variante Instruct de 7B, mas os resultados continuam específicos ao tag local, quantização e versão instalados. [Qwen2.5-Coder-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct)

## Execução e limites

```sh
uv run python scripts/prompt_effort_plan_study.py plan
uv run python scripts/prompt_effort_plan_study.py run --model qwen2.5-coder:7b
```

O run salva prompts, respostas, chamadas, eventos e hashes do fixture em `.zerocoding/studies/m2/prompt-effort/runs/<run-id>/`. `docs/prompt-effort-results.json` contém o resumo por condição. Se for interrompido, o run pode ser retomado com `--resume-run-dir` apontando para a mesma pasta.

Com duas repetições, os resultados são direcionais, não estatisticamente conclusivos. Effort só pode fazer diferença quando a tarefa usa o orçamento maior ou precisa de mais rodadas. O run não mede RAM/VRAM e não compara modelos. Se o protocolo de ferramenta continuar falhando, isso será registrado como problema distinto da qualidade do texto do system prompt.

## Resultados

Run `20261012T200923Z-9dca1f`, com `qwen2.5-coder:7b` já instalado e Ollama 0.40.0. Foram feitas duas repetições por condição, 24 respostas ao todo. Não houve alteração do prompt de produção. O resumo versionado não inclui respostas nem traces completos.

### Prompt e budgets

| Tarefa / condição | Sucesso objetivo | Tokens de entrada / saída (medianas) | Orçamento de saída / rodadas |
|---|---:|---:|---:|
| Fato do projeto — atual + Low | 2/2 | 81 / 6 | 512 / 3 |
| Fato do projeto — reformulado + Low | 2/2 | 109 / 7 | 512 / 3 |
| Fato do projeto — reformulado + Medium | 2/2 | 109 / 7 | 1.024 / 6 |
| Fato do projeto — reformulado + High | 2/2 | 109 / 7 | 2.048 / 8 |
| Fato do projeto — reformulado + Medium + Ultrathink | 2/2 | 137 / 7 | 2.048 / 8 |
| Busca/leitura — atual + Low | 0/2 | 423 / 36,5 | 512 / 3 |
| Busca/leitura — reformulado + Low | 0/2 | 447 / 36 | 512 / 3 |
| Busca/leitura — reformulado + Medium | 0/2 | 447 / 36 | 1.024 / 6 |
| Busca/leitura — reformulado + High | 0/2 | 447 / 36 | 2.048 / 8 |
| Busca/leitura — reformulado + Medium + Ultrathink | 0/2 | 475 / 35,5 | 2.048 / 8 |

Na pergunta direta, a resposta correta foi estável em todos os budgets, então essa tarefa simples não revelou ganho de Medium, High ou Ultrathink. Na busca, nenhuma condição concluiu `read_file`; o modelo devolveu JSON de ferramenta como texto comum ou apenas disse que iria procurar. A reformulação pediu explicitamente chamadas nativas e proibiu expor JSON cru, mas não resolveu o comportamento. O check granular `explains_sum` passou em algumas respostas por ecoar palavras do pedido e é permissivo demais; a conclusão geral continua 0/2 porque a leitura não ocorreu.

O novo system prompt acrescentou 28 tokens de entrada na pergunta direta (+34,6%) e 24 na tarefa com ferramentas (+5,7%) nas medianas observadas. Ultrathink acrescentou 28 tokens sobre a variante reformulada sem Ultra e não elevou a taxa de acerto nessas tarefas. Isso descreve apenas estes pedidos e este modelo; duas repetições não demonstram equivalência geral nem que o prompt atual seja ótimo.

### Plan mode

| Condição | Tarefa concluída | Observações |
|---|---:|---|
| Reformulado + Low, Plan Off | 0/2 | Não chamou ferramenta nativa nem pediu aprovação de escrita; terminou após uma resposta textual com JSON cru. |
| Reformulado + Low, Plan On | 0/2 | Não apresentou plano. Também não chamou ferramenta nem pediu aprovação; nenhum acesso de escrita/comando ocorreu. |

Plan On reduziu a entrada mediana de 464 para 394 tokens ao omitir schemas de escrita/comando. Separadamente, o probe direto do executor passou os quatro checks: gravação bloqueada, comando bloqueado, workspace intacto e callback de aprovação não chamado. Isso valida o guard determinístico do Plan; não valida o ciclo conversacional de planejamento, já que o modelo não conseguiu iniciar nem uma leitura.

### Effort e desempenho

Neste adaptador Ollama, `native_effort_supported` é falso para todos os grupos: Low/Medium/High alteram os tetos de saída e rodadas, mas não acionam um controle nativo de raciocínio do modelo. A documentação da API do Ollama descreve `think` para modelos que suportam esse campo, porém o adaptador usado neste experimento não o envia. [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md)

Os tempos foram muito instáveis e não monotônicos: na pergunta direta, a mediana variou de aproximadamente 0,37 s (atual + Low) a 13,52 s (reformulado + Medium + Ultrathink), apesar de todas essas condições produzirem respostas curtas corretas. A busca também variou de cerca de 7,59 a 17,10 s sem uma única leitura concluída. A coleta atual não permite atribuir essas diferenças ao texto, budget, carregamento do modelo ou outra variação do runtime; latência não é evidência para escolher uma condição neste run.

## Conclusão provisória

- **Não substituir o prompt de produção agora.** O alternativo empatou no único caso direto bem-sucedido, custou mais tokens e não corrigiu chamadas de ferramenta. A amostra não prova que o prompt atual seja ideal nem que uma reformulação bem medida não possa melhorar tarefas reais.
- **Não tratar os budgets atuais como níveis de raciocínio.** Nesta integração, eles controlam apenas saída/rodadas. Ultrathink não trouxe ganho observável nos casos usados e adicionou tokens.
- **Plan está seguro no executor, mas não validado como experiência do agente.** O modelo não chamou leitura, não produziu plano e não chegou a uma decisão de aprovação/recusa.
- **O bloqueio observado é do protocolo de chamadas de ferramenta.** As APIs do Ollama documentam chamadas estruturadas; aqui o Qwen respondeu com JSON em texto comum, sem `tool_calls` nativas. Essa incompatibilidade precisa ser tratada como limitação do runtime/modelo antes de usar esses trials para julgar capacidade de programação ou prompt. [Ollama — tool calling](https://github.com/ollama/ollama/blob/main/docs/capabilities/tool-calling.mdx)

O resultado é direcional, específico a `qwen2.5-coder:7b` neste Ollama e limitado a três pedidos sintéticos. Não compara RAM/VRAM, não testa edição executada e não altera o escopo do M2. O M3 continua aguardando a revisão e a declaração explícita do usuário.

## Extensão comparável: Qwen3-8B e Qwen3.5-9B

Por solicitação do usuário, a mesma matriz (mesmos prompts, tarefas, temperatura, sementes pareadas, budgets, duas repetições e guards) foi executada nos dois candidatos abaixo de 12B, sem repetir o controle 7B e sem testar o Gemma 4 12B. O Ollama informado é 0.40.0. O modelo de 8B foi baixado durante esta rodada; o 9B já estava instalado.

| Modelo | Fato do projeto | Busca/leitura e explicação | Plan Off: proposta e recusa | Plan On: plano conversacional | Guard do executor |
|---|---:|---:|---:|---:|---:|
| Qwen2.5-Coder-7B (controle anterior) | 10/10 | 0/10 | 0/2 | 0/2 | passou |
| Qwen3-8B | 7/10 | 9/10 | 2/2 | 0/2 | passou |
| Qwen3.5-9B | 10/10 | 4/10 end-to-end; `read_file` concluiu em 10/10 | 2/2 | 0/2 | passou |

Para o Qwen3-8B, a tarefa de leitura falhou uma vez em Low por limite de rodadas; as demais condições concluíram a leitura e explicaram o símbolo. A resposta de fato foi menos estável com o prompt reformulado (1/2 em Low, Medium e High), mas 2/2 com o prompt atual e com Medium + Ultrathink. Isso não sustenta uma conclusão geral de que o Ultra é melhor: são duas repetições de um cálculo simples.

No Qwen3.5-9B, o modelo iniciou chamadas nativas e leu o arquivo em todas as dez tentativas de busca/leitura, mas em seis delas o adapter registrou texto final vazio. `OllamaProvider.chat()` só mapeia `message.content` e não preserva o campo `thinking`; portanto, a pontuação textual mede o modelo através do adapter atual e não permite atribuir essa falha somente ao modelo. As duas condições de leitura que expuseram conteúdo final foram a baseline de prompt atual + Low e reformulado + Medium + Ultrathink. O caso direto com contexto passou 10/10.

Plan Off pediu aprovação para escrita nas quatro tentativas dos modelos 8B/9B, a recusa foi registrada e nenhum arquivo foi escrito. Em Plan On, ambos preservaram o workspace, evitaram aprovação e escrita/comando, mas nenhum dos quatro trials avaliados apresentou um plano. O Qwen3-8B informou incorretamente que `src/settings.py` não existia; o Qwen3.5-9B encerrou com resposta final vazia. O guard direto do executor passou em todos os runs, validando bloqueio, não a experiência conversacional do Plan.

Os tempos medianos por condição variaram aproximadamente de 3 a 22 segundos no 8B e de 3,5 a 53 segundos no 9B. Não foram coletados RAM/VRAM nem telemetria da GPU; os tempos incluem variação de thinking, geração e chamadas. O adapter não envia `think` nem effort nativo, então Low/Medium/High continuam sendo budgets do agente. Não se deve interpretar estas medições como comparação controlada de velocidade ou de thinking nativo.

IDs e traces locais: Qwen3-8B `20261012T204700Z-9bb495`; Qwen3.5-9B `20261012T212852Z-831267`. Os agregados completos estão no JSON versionado; prompts, respostas e eventos continuam nos diretórios ignorados em `.zerocoding/studies/m2/prompt-effort/runs/`. A execução não escolhe um modelo default, não altera o prompt de produção e não inicia M3. O teste de 12B permanece deliberadamente pendente.
