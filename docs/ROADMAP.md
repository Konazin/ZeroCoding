# Roadmap do ZeroCoding

Este roadmap orienta a evolução do ZeroCoding como agente de programação para modelos pequenos e PCs leves/intermediários. A referência de hardware é o Ryzen 5 4600G, 16 GB de RAM e RX 5700. A prioridade é manter um agente útil em uma janela de contexto pequena, com resposta rápida e comportamento verificável.

## Baseline

- A branch `development` parte da `main` no commit `2dda833` e preserva as alterações locais existentes no início deste roadmap.
- O projeto já tem CLI/TUI em Python com Rich e prompt_toolkit, configuração por YAML, provedores Ollama e OpenAI-compatible, sessões, skills e contexto explícito.
- A implementação local já inclui orçamento estimado de contexto, chamadas estruturadas de ferramentas e aprovação para gravações/comandos. A suíte precisa ser executada em um ambiente com Python antes de considerar esses recursos estabilizados.
- O repositório `../zerocode` contém documentação, plugins e mods, mas não o runtime do Claude Code. A inspiração será baseada em padrões observáveis e documentação pública, sem pressupor acesso ao prompt interno.

## Marcos

### M1 — Visual e fluxo do terminal

**Objetivo:** adaptar a experiência visual e o fluxo de uso do Claude Code à identidade ZeroCoding, melhorando a leitura do transcript e a interação durante o trabalho do agente.

**Estado:** concluído após a revisão final com o usuário em 2026-10-12. Rich + prompt_toolkit é a interface de produção; Textual permanece como protótipo opcional. O usuário autorizou o início do M2.

**Entregas:**

- Usar Rich + prompt_toolkit na experiência de produção e manter a navegação clássica por scrollback. O protótipo Textual pode continuar disponível para comparação sem ser dependência de instalação normal.
- Limpar a tela visível uma vez ao iniciar o modo interativo, depois exibir fantasma pixelado em roxo, nome/versão, provedor/modelo, modo e workspace. Não limpar a tela em `-m/--message`.
- Compor o prompt entre duas linhas horizontais discretas, ambas ocupando a largura do terminal. O campo inicia com uma linha, cresce conforme o texto até seis linhas e então rola internamente; `Enter` envia, `Ctrl+J` cria uma nova linha. Abaixo da linha inferior, alinhar à direita somente `Effort`; Plan, Ultra, modelo e orçamentos completos ficam em `/status`.
- Usar fantasma original sem nome próprio, grande na abertura e compacto durante a conversa, com fallback ASCII. Animar dois frames a 4 fps apenas enquanto o agente trabalha; mostrar estados estáticos para idle, approval, success e error, mantendo o brilho como elemento separado.
- Escolher uma frase curta em inglês por etapa de raciocínio e substituir por status factual quando uma ferramenta estiver realmente em execução. Mostrar tempo decorrido e `Worked for Ns` após a resposta completa; não simular streaming, cancelamento ou raciocínio interno.
- Diferenciar mensagens do usuário e do agente, mostrar eventos de ferramenta de forma compacta e apresentar diff/comando completo antes de cada aprovação. A confirmação aceita `Y`, `N` e `Esc`, com recusa como padrão.
- Manter compositor multilinha, autocomplete slash apenas no início da entrada, histórico persistente por workspace limitado aos últimos 200 prompts e textos visíveis em inglês, mantendo os identificadores de comandos existentes.
- Acrescentar eventos internos opcionais ao loop de ferramentas para início, pedido de aprovação, conclusão, recusa e erro, sem alterar o contrato do provedor.
- Incluir `/plan [on|off]` com esquemas de ferramentas somente leitura e bloqueio também no executor; `/ultrathink [on|off]` aumenta saída em 1.024 tokens e duas rodadas (máximo de 12) e acrescenta uma instrução curta, sem expor raciocínio privado.
- Incluir `/effort [low|medium|high]` com orçamentos configuráveis em YAML. Perfis padrão: 512/3, 1.024/6 e 2.048/8 (tokens de saída/rodadas); esforço nativo só é enviado quando o provedor declara suporte. Ultrathink soma seu orçamento ao perfil ativo.
- Persistir Plan, Ultra, Effort, provedor, modelo, modo, skills, histórico e contexto por sessão. `/resume` restaura esses valores; `/new` usa defaults configurados, Plan/Ultra desligados e Medium. `/model` e `/mode` alteram a sessão sem sobrescrever defaults; modos internos mapeiam code→Medium, fast→Low e reason/smart→High, enquanto perfis personalizados preservam esforço.
- Preservar configurações antigas: `max_output_tokens` e `max_tool_rounds` existentes alimentam o perfil Medium se `effort_profiles` ainda não estiver definido; perfis explícitos em YAML prevalecem.
- Registrar decisões e protótipos locais em `docs/m1-stack-comparison.md`; a dependência Textual fica opcional depois da escolha de Rich.

**Critérios de saída:**

- Os fluxos de pergunta, leitura/busca, aprovação/recusa e erro são visualmente distinguíveis e não sugerem ações que não ocorreram.
- Prompt e barra de estado permanecem legíveis a 40, 80 e 120 colunas; a animação não desloca a composição do prompt.
- Plan bloqueia gravações e comandos tanto nos esquemas apresentados como na execução direta da ferramenta. Os três esforços usam os orçamentos definidos e Ultrathink respeita o teto de 12 rodadas.
- Sessões antigas continuam retomáveis com os defaults de controle (`Plan off`, `Ultra off`, `Medium`); sessão nova usa os defaults configurados de provedor/modelo/modo.
- M1 foi concluído após implementação e revisão manual pelo usuário em 2026-10-12.

### M2 — Estudo do system prompt e do contexto

**Objetivo:** entender a função e o custo de cada parte enviada ao modelo antes de decidir o prompt mínimo e a política de contexto.

**Estado:** concluído por declaração do usuário em 2026-10-14; o M3 está liberado. Registro histórico: os dois estudos originais de prompt/contexto foram concluídos e o comparativo solicitado de modelos abaixo de 12B também foi executado; revisão do usuário concluída. O estudo principal teve 51 trials pontuados. A matriz curta de prompt/effort/Plan foi rodada com 24 respostas cada em Qwen2.5-Coder-7B, Qwen3-8B e Qwen3.5-9B (72 no total). Relatórios: `docs/prompt-study.md`, `docs/prompt-effort-study.md` e `docs/model-baseline.md`; agregados: `docs/prompt-study-results.json` e `docs/prompt-effort-results.json`. O Qwen3-8B completou leitura com explicação em 9/10; o Qwen3.5-9B concluiu `read_file` em 10/10, mas o adapter reportou resposta final vazia em seis tentativas. Plan On preservou o workspace e passou os guards diretos, mas nenhum modelo produziu plano nas duas repetições. Esses resultados não escolhem modelo nem prompt: o adapter atual não envia thinking nativo, as respostas foram duas por condição e não houve medição de RAM/VRAM. `qwen3:8b` foi baixado; `qwen3.5:9b` já estava disponível; `gemma4:12b` também está instalado, mas não foi testado conforme solicitado. Prompt, baseline e budgets de produção permanecem inalterados. O M3 ainda não começou, mas está liberado.

**Entregas:**

- Inventariar as partes reais do prompt ZeroCoding: instrução fixa, controles condicionais, skills, contexto explícito, histórico, pedido atual, schemas/fallback e resultados de ferramentas.
- Mapear features públicas de referência e catálogo `../zerocode` para necessidade, custo/dependência, camada de código e marco; MCP, subagents, plugins e hooks ficam depois do núcleo salvo necessidade comprovada.
- Executar `scripts/prompt_study.py` com um modelo `qwen2.5-coder:7b` já instalado; nunca baixar modelo automaticamente. Usar workspace sintético temporário e negar toda escrita/comando.
- Comparar baseline e variante compacta combinada nos quatro cenários, além de ablações unitárias somente nos cenários relacionados; repetir cada condição três vezes e aquecer separadamente.
- Registrar mensagens e respostas brutas localmente em `.zerocoding/studies/m2/`; versionar apenas métricas agregadas, sem respostas ou traces.
- Obter avaliação humana cega de correção, completude, seguimento de instruções e segurança. Os 51 scores foram registrados; o relatório aponta limites na avaliação cega do cenário direto e uma anotação incompatível com a resposta associada. Checks objetivos são auxiliares, sem limiar automático de adoção.
- Executar uma matriz complementar curta com prompt atual + Low, prompt novo + Low/Medium/High/Ultrathink e Plan Off/On, usando workspace descartável e guards seguros; registrar quando a falha de ferramenta impedir avaliar comportamento de ponta a ponta.
- Manter o prompt de produção inalterado durante o estudo. Apresentar as evidências e alternativas antes de propor arquitetura ou implementação do M3.

**Critérios de saída:**

- O modelo/local endpoint está disponível e os quatro casos concluem três repetições por condição aplicável; se o pré-requisito não existir, registra-se a limitação sem download.
- `docs/prompt-study.md` e seu agregado reportam estimativas por componente separadas das contagens reais agregadas do provedor, latência mediana/pior, taxa de checks e notas humanas cegas; `docs/prompt-effort-study.md` e seu agregado registram resultados do comparativo curto de prompt, budgets e Plan.
- O relatório explica o propósito, a estimativa de custo, o efeito observado e o trade-off de cada bloco, e propõe inclusão dinâmica onde os dados sustentarem.
- O relatório recomenda manter ou ajustar os orçamentos atuais de 4.096 tokens de entrada e 1.024 de saída com base nos resultados.
- O usuário revisou o relatório e declarou M2 concluído em 2026-10-14, liberando o M3. Nenhuma mudança de prompt passa a produção por decisão automática.

### M3 — Arquitetura leve do agente

**Objetivo:** decompor o runtime em partes pequenas e testáveis, inspirado nos limites funcionais do Claude Code e dimensionado para modelos locais menores.

**Entregas:**

- Separar montagem/orçamento do contexto, loop do agente, interface de provedores, registro de ferramentas e permissões, sessões e apresentação no terminal.
- Manter um protocolo normalizado de resposta do provedor para texto, chamadas de ferramenta e uso de tokens.
- Carregar apenas instruções, skills e esquemas de ferramentas relevantes à tarefa; manter histórico e contexto explicitamente limitados.
- Manter execução local em um único processo Python e evitar novas dependências/frameworks sem benefício medido.

**Critérios de saída:**

- Os componentes principais podem ser testados isoladamente com provedores simulados.
- Os limites de contexto, saída e rodadas são aplicados em todas as chamadas.
- Nenhum módulo injeta histórico global ou conteúdo de outra sessão no prompt atual.

### M4 — Fluxo de programação confiável

**Objetivo:** consolidar um ciclo de trabalho capaz de inspecionar um projeto, propor mudanças e executar ações com controle explícito do usuário.

**Entregas:**

- Descoberta, leitura e busca limitadas ao workspace.
- Proposta de edição apresentada como diff; nenhuma gravação ocorre sem aprovação explícita.
- Comandos são apresentados antes da execução e exigem aprovação explícita.
- Chamadas inválidas, recusas, falhas do provedor e limite de rodadas retornam resultados compreensíveis ao modelo e ao usuário.
- Sessões novas e retomadas preservam apenas seu próprio histórico e contexto.

**Critérios de saída:**

- Testes cobrem aprovação e recusa de diff/comando, bloqueio de caminhos fora do workspace, falhas de ferramenta, limite de rodadas e isolamento de sessão.
- Uma tarefa de leitura/busca e uma tarefa de edição proposta podem ser concluídas pelo ciclo do agente sem executar ação recusada.

### M5 — Avaliação em modelos e hardware-alvo

**Objetivo:** verificar qualidade, velocidade e uso de memória em configurações que representem PCs leves e intermediários.

**Entregas:**

- Partir do conjunto candidato revisado em `docs/model-baseline.md` (Qwen3-8B, Qwen3.5-9B, Gemma 4 12B e Qwen2.5-Coder-7B como controle); expandir para outros modelos somente se os primeiros resultados mostrarem uma lacuna.
- Repetir os casos de M2/M4 três vezes e registrar mediana e pior caso.
- Medir tokens de entrada/saída, tempo até a primeira resposta, tokens por segundo, duração total, RAM/VRAM, validade das chamadas e conclusão das tarefas.
- Atualizar `docs/model-evaluation.md` com versões, quantizações, configurações e resultados reproduzíveis.

**Critérios de saída:**

- O relatório identifica modelos/configurações recomendados para a máquina-alvo e deixa claras as limitações observadas.
- Todo aumento de prompt, contexto ou dependências é avaliado contra qualidade, latência e memória.

### M8 — Integridade e privacidade das sessões locais

**Estado:** implementação local concluída e suíte automatizada aprovada. A confirmação da instalação empacotada pela CI está pendente. O mega teste M7.2–M7.4 foi depois executado por autorização do usuário e seus gates não passaram; evidências em [`MEGA-TEST-M7-M8-2026-10-16.md`](MEGA-TEST-M7-M8-2026-10-16.md) e [`ROADMAP-m8.md`](ROADMAP-m8.md).

## Ordem e escopo

M1 e M2 estão concluídos (M2 declarado pelo usuário em 2026-10-14). O M3 está liberado para início. Os resultados do M2 orientam as decisões de M3. M4 depende dos contratos definidos em M3. M5 mede o fluxo integrado de M4 e alimenta novas decisões de contexto e arquitetura. M6 e M7 têm roadmaps específicos (`ROADMAP-m6.md` e `ROADMAP-m7.md`); M8 teve implementação e validação local concluídas, com instalação empacotada pela CI pendente.

O núcleo inicial cobre TUI, agente, ferramentas, contexto, sessões, permissões e desempenho. M8 foi implementado antes do mega teste M7 por autorização explícita; o teste foi executado posteriormente, mas os gates M7.2–M7.4 ainda precisam de correções e nova validação. MCP, subagentes, plugins e hooks ficam fora desses marcos e só entram em um roadmap posterior se houver necessidade comprovada e custo aceitável.
