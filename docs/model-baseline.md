# Proposta de baseline de modelos locais

**Estado:** candidatos pesquisados; comparativo inicial concluído em 2026-10-12. `qwen3:8b` foi baixado e testado, `qwen3.5:9b` já estava instalado e foi testado. `gemma4:12b` está instalado, mas permanece sem teste conforme solicitado. Nenhum modelo foi escolhido como default.  
**Data da pesquisa:** 2026-10-12.  
**Escopo:** open weights locais nas faixas próximas de 7B, 9B e 12B, com tool calling e algum controle documentado de raciocínio. A recomendação não inicia a arquitetura M3 nem substitui a avaliação prática de modelos prevista para M5.

## O que significa “effort” para esses modelos

Não encontrei nesses candidatos um parâmetro local universal com níveis nativos `low`, `medium` e `high` equivalente ao controle de effort do Claude. O que eles documentam é principalmente um controle de **thinking ligado/desligado**. O CLI ainda pode oferecer perfis Low/Medium/High por limite de saída e rodadas, mas precisa descrever isso como orçamento do agente; só deve dizer “native thinking” quando ligar o controle específico do modelo. O [Ollama expõe `think: true/false` na API](https://github.com/ollama/ollama/blob/main/docs/api.md) para modelos que suportam esse modo.

## Candidatos

| Faixa / papel provisório | Modelo e formato local observado | Thinking nativo documentado | Tool calling documentado | Avaliação para ZeroCoding |
|---|---|---|---|---|
| **8B — base rápida** | **Qwen3-8B**, Ollama `qwen3:8b`, **5,2 GB** observado localmente | Sim. Alterna thinking/non-thinking; a integração Ollama documenta `think: true/false`. Isso é binário, não effort graduado. | Sim. O card oficial do Qwen recomenda Qwen-Agent para templates/parsing de chamadas; a documentação Ollama mostra o ciclo completo com `tools`, `tool_calls` e `think`. | Teste local: leitura e explicação concluídas em 9/10; fatos diretos em 7/10; Plan conversacional não produziu plano. Promissor no loop de ferramenta, ainda sem evidência para virar default. [Card Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B), [tags Ollama](https://ollama.com/library/qwen3/tags), [tool calling Ollama](https://docs.ollama.com/capabilities/tool-calling) |
| **9B — base balanceada** | **Qwen3.5-9B** (Ollama informa 9,7B), `qwen3.5:9b`, **6,6 GB** observado localmente | Sim, porém diferente do Qwen3: thinking vem ligado por padrão e pode ser desligado por parâmetro de template no serving compatível. O card não documenta níveis Low/Medium/High. | Sim. O card descreve forte uso de ferramentas e mostra parser `qwen3_coder` com SGLang/vLLM para chamadas estruturadas. | Teste local: fato direto 10/10 e `read_file` 10/10, mas resposta explicativa apareceu em só 4/10; o adapter atual não expõe `thinking`. É candidato condicionado a corrigir/diagnosticar o mapeamento do provider. [Card Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B), [tags e tamanho Q4 Ollama](https://ollama.com/library/qwen3.5/tags), [relato histórico no Ollama](https://github.com/ollama/ollama/issues/14745) |
| **12B — teto de qualidade local** | **Gemma 4 12B Unified**, Ollama `gemma4:12b-it-q4_K_M`, cerca de **8,0 GB**; variante QAT listada em **7,2 GB**. Tag `gemma4:12b` e tamanho local de **7,6 GB** observados; ainda não testado. | Sim. Thinking é ativado com o token `<|think|>` na mensagem system ou com o controle equivalente do runtime. Não há níveis graduados. | Sim. Gemma 4 foi treinada com tokens específicos de declaração/chamada/retorno de ferramenta e a documentação descreve o fluxo estruturado. O adapter/runtime precisa preservar o formato e o estado exigido entre chamadas. | Bom candidato para medir o teto de qualidade, mas **não default** para a máquina de referência: a RX 5700 tem 8 GB de VRAM e a quantização Q4 ocupa aproximadamente esse total antes do cache e do runtime. Esperar offload para RAM ou contexto menor; isso pode reduzir velocidade. [Thinking Gemma](https://ai.google.dev/gemma/docs/capabilities/thinking), [tool calling Gemma 4](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4), [tamanhos Ollama](https://ollama.com/library/gemma4/tags) |
| **7B — controle legado de código** | **Qwen2.5-Coder-7B-Instruct**, Ollama `qwen2.5-coder:7b-instruct`, cerca de **4,7 GB** | Não encontrei controle nativo de thinking/effort documentado para esta variante. O Ollama a lista com capacidade de ferramentas, mas isso não é controle de raciocínio. | Capacidade de ferramentas listada pelo Ollama; no estudo M2 do ZeroCoding, o modelo emitiu JSON como texto e não concluiu chamadas. | Mantê-lo como **baseline de regressão**, pois já foi testado e é código-específico. Não deve ser apresentado como modelo que cumpre ambos os requisitos até passar o teste de chamadas com o adapter/runtime escolhido. [Ollama Qwen2.5-Coder 7B](https://ollama.com/library/qwen2.5-coder:7b-instruct) |

### Leitura para a máquina de referência

Na máquina citada pelo projeto (Ryzen 5 4600G, 16 GB RAM, RX 5700 com 8 GB), Qwen3-8B Q4 é a opção mais conservadora para inferência local. Qwen3.5-9B Q4 já deixa menos espaço livre para cache e buffers. Gemma 4 12B Q4 não cabe confortavelmente na VRAM de 8 GB; QAT reduz o artefato de pesos para cerca de 7,2 GB, mas ainda deixa pouca margem para contexto, buffers e runtime. O tamanho do arquivo de pesos não é o total de memória em execução.

Esses limites sugerem iniciar com contexto explícito moderado (por exemplo, 8K tokens) e aumentar só se RAM/VRAM e latência forem aceitáveis. As janelas máximas publicadas de 40K/256K não devem virar o valor padrão do CLI: KV cache cresce com contexto, e a meta do ZeroCoding é responder rápido com prompt pequeno.

## Proposta de conjunto de trabalho

**Candidatos para o piloto, sem seleção definitiva:**

1. `compact`: Qwen3-8B Q4_K_M — default local candidato.
2. `balanced`: Qwen3.5-9B Q4_K_M — candidato de maior capacidade ainda próximo do limite de VRAM.
3. `quality`: Gemma 4 12B QAT ou Q4 — comparação de teto, com possível offload e sem promessa de velocidade.
4. `legacy-code`: Qwen2.5-Coder-7B-Instruct — controle para distinguir regressões de modelo das regressões de provider/parser.

Até agora não há base para declarar Qwen3-8B ou Qwen3.5-9B como default. O primeiro teve um loop de leitura confiável, mas respostas diretas inconsistentes; o segundo foi consistente em fatos e iniciou chamadas estruturadas, porém o texto final não chega ao agente em várias condições. `gemma4:12b` estava disponível localmente, mas não foi executado neste ciclo.

O CLI deve carregar **um modelo local por vez**. Os nomes são perfis de seleção, não promessa de subagentes ou carga paralela. Trocar o modelo pode exigir descarregar/recarregar pesos; o feedback da TUI deve dizer que o modelo está carregando, não sugerir que ele está pronto antes do provider confirmar.

## Consequências para a arquitetura do CLI

O projeto já normaliza `content`, `tool_calls` e uso básico, mas hoje não mantém metadados de thinking no `ProviderTurn`; o executor também serializa chamadas/resultados num formato genérico. `OllamaProvider.chat()` não envia hoje o campo `think`, e `native_effort_kwargs()` do adaptador continua sem implementação; `OpenAICompatibleProvider` também não mapeia parâmetros específicos de thinking. Para as famílias acima, o catálogo do modelo precisa informar ao provider como mapear capabilities e formatos.

Um `ModelProfile` futuro deveria declarar, no mínimo:

- identificador do catálogo e nome do modelo no runtime;
- família/template de chat e parser de tool calls;
- suporte de thinking: `unsupported`, `toggle`, `always_on` ou controle específico;
- mapeamento de effort: parâmetro nativo, quando existir, separado de tokens/rodadas do agente;
- suporte a tool calling e formato de mensagens de chamada/resultado;
- runtime e versão mínima verificados, janela de contexto testada e quantização local;
- licença/termos de distribuição e estado de validação do ZeroCoding.

O ciclo de ferramenta precisa preservar chamadas nativas, IDs, argumento estruturado, resultado nomeado e qualquer metadado que o modelo/runtime exija no turno seguinte. O provider Ollama atual também descarta ID/nome do resultado de ferramenta. Isso é especialmente relevante para modelos que alternam thinking e tools. O parser compacto `<tool_call>{...}</tool_call>` atual não substitui parsers próprios de famílias com formatos diferentes. A autorização de write/command segue no executor determinístico, fora do modelo.

O `/effort` deve mostrar o efeito real do perfil no modelo ativo. Exemplo de linguagem honesta: `Low · thinking off · 512 output tokens · 3 tool rounds`; se o modelo não suportar controle nativo, `Low · budget only`. Não expor ou armazenar chain of thought como transcript visível.

## Próximas validações

1. Diagnosticar o campo de resposta do Qwen3.5-9B no Ollama e preservar o metadado de thinking necessário antes de repetir a matriz para esse modelo.
2. Repetir as tarefas de leitura/Plan no Qwen3-8B após revisar o erro de caminho e a ausência do plano, sem alterar automaticamente o prompt de produção.
3. Manter o Qwen2.5-Coder-7B como controle e só então comparar os candidatos em latência/RAM/VRAM com medições dedicadas. Os runs atuais não coletaram RAM/VRAM, tokens por segundo nem tempo até primeiro token.
4. Deixar Gemma 4 12B fora até nova solicitação; ele estava instalado, mas o usuário pediu para não testá-lo nesta rodada.

O estudo comparável com 8B/9B está em [`prompt-effort-study.md`](prompt-effort-study.md) e seus números em [`prompt-effort-results.json`](prompt-effort-results.json). As duas execuções usaram o mesmo harness que o Qwen2.5-Coder, mas os resultados medem o modelo junto do provider/runtime; não isolam o modelo. O teste não escolhe um default e não inicia M3.

## Fontes técnicas

- [Qwen3-8B — card e modos thinking/non-thinking/tool calling](https://huggingface.co/Qwen/Qwen3-8B)
- [Ollama — API `think` e tool calling](https://github.com/ollama/ollama/blob/main/docs/capabilities/tool-calling.mdx)
- [Qwen3.5-9B — card, tool use e parser de serving](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Gemma 4 — thinking](https://ai.google.dev/gemma/docs/capabilities/thinking)
- [Gemma 4 — function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4)
- [Ollama — variantes e tamanhos Gemma 4](https://ollama.com/library/gemma4/tags)
- [Qwen2.5-Coder 7B — variante de controle](https://ollama.com/library/qwen2.5-coder%3A7b-instruct)
