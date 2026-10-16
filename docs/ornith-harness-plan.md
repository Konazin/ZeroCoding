# Harness do Ornith com llama.cpp

**Status:** implementado e validado nesta máquina na branch `development`; M2 continua aberto para revisão do usuário.

## Objetivo

Integrar o Ornith-1.5-9B Q5_K_M como único modelo padrão do ZeroCoding, servido localmente pelo `llama-server` com backend Vulkan. A primeira etapa concentra-se na confiabilidade do loop de ferramentas e em um caminho reproduzível de instalação. O M2 continua pendente de revisão do usuário; este trabalho não fecha o marco nem inicia o M3.

Modelo local escolhido: `/mnt/jogos/huggingFaceModels/Ornith-1.5-9B-Q5_K_M.gguf` (6,852,928,384 bytes). Alias do servidor: `ornith-1.5-9b-q5-k-m`. O ambiente atual tem `llama-server` 0.6.0, build 11429, e detecta a RX 5700 como `Vulkan0`.

## Decisões de implementação

- Adicionar provider explícito `llama_cpp` usando o transporte OpenAI-compatible já existente; sem bindings ou dependências Python adicionais.
- Usar `http://127.0.0.1:8080/v1` e o alias do modelo nos defaults. O caminho do GGUF fica no comando do servidor, não na configuração compartilhada.
- Apontar todos os modos internos para o mesmo Ornith. `fast`, `reason` e `smart` continuam diferenciando budgets de effort, sem trocar o modelo.
- Usar Jinja e o chat template do GGUF para chamadas de ferramenta. Enviar `reasoning_effort` por requisição para llama.cpp; o `/status` explicita que o uso nativo depende do template do modelo.
- Preservar `reasoning_content` apenas na memória de uma rodada se necessário para continuar uma chamada de ferramenta. Não exibir nem salvar o conteúdo de raciocínio em sessões.
- Se uma rodada inicial vier vazia, repetir a mesma solicitação uma vez. Se continuar vazia, mostrar erro claro. Depois de uma chamada de ferramenta executada, não repetir ações automaticamente.
- Manter os guards atuais: Plan é somente leitura; gravações e comandos exigem aprovação.
- Usar o perfil publicado pelo Ornith para coding preciso: temperature 0.6, top-p 0.95, top-k 20, presence penalty 0 e repetition penalty 1. Contexto inicial do servidor: 8192 tokens, acima do budget combinado padrão de 5120. Usar uma slot (`-np 1`) para o uso individual do CLI.
- Priorizar Vulkan, selecionando `Vulkan0` na RX 5700. Documentar CPU como fallback manual com `-ngl 0`, sem troca silenciosa.
- O harness encaminha `reasoning_effort`, mas o template atual do Ornith não anuncia esse recurso; Low/Medium/High mudam os budgets do harness, e o campo nativo não deve ser tratado como controle efetivo neste modelo.

## Documentação a manter

- README: passos portáveis para Linux e uma seção NixOS, build/diagnóstico Vulkan, comando de servidor, configuração do ZeroCoding e fallback CPU.
- `context.md` na raiz: missão do projeto, stack, modelo atual, arquitetura, limites de segurança e estado do roadmap para uso como contexto futuro.
- Este arquivo registra o plano e a decisão de manter um único modelo nesta etapa.

## Validação concluída

- Testes automatizados cobrem parsing de tool calls, preservação de IDs e resultados, chamadas em múltiplas rodadas, raciocínio privado, effort e retry de resposta vazia.
- Smoke no Ornith usa workspace temporário para resposta direta, leitura/busca com ferramenta, Plan/recusa de escrita e conexão/alias do servidor.
- Testes: `uv run python -m unittest discover -s tests -p 'test_*.py'` — 45 testes passaram; `uv run python -m py_compile src/zerocoding/**/*.py` e `git diff --check` passaram.
- Servidor: llama.cpp 0.6.0, build b11429, endpoint `/health` respondeu `ok`; `/props` confirmou o alias, o GGUF Q5_K_M, contexto de 8192, perfil de amostragem esperado e quatro slots automáticas na execução inicial. O README agora fixa uma slot com `-np 1`.
- Hardware: `Vulkan0` identificado como AMD Radeon RX 5700. Durante o smoke, a leitura DRM variou entre 7,05 e 7,18 GB usados de 8,57 GB; `llama-server --list-devices` mostrou cerca de 1,27 GiB livres. O processo usou Vulkan, mas a contagem exata de camadas offloaded não foi confirmada, então não é registrada como fato.
- Desempenho observado em requests curtas: processamento de prompt entre 112 e 123 tokens/s e geração entre 17,8 e 18,9 tokens/s. Varia com cache e tamanho do request; não é benchmark comparativo.
- Smoke real: resposta direta, chamada de `read_file` com resposta final correta e Plan mode com arquivo inalterado. O raciocínio retornado durante a ferramenta não apareceu na resposta nem no histórico da sessão. Low, Medium e High foram aceitos; isso não prova efeito nativo e o template reportou `supports_reasoning_effort: false`.
- Não executar matriz comparativa de modelos nem registrar respostas ou traces privados no repositório.

## Referências técnicas

- [Ornith: instruções e parâmetros recomendados](https://github.com/ornith-ai/Ornith-1#quickstart)
- [llama.cpp server: API, tool calling e reasoning](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp: build Vulkan](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#vulkan)

## Registro de implementação

O provider `llama_cpp` usa o transporte OpenAI-compatible existente, sem binding novo. O default aponta para o Ornith local; todos os modos built-in usam o mesmo alias. Respostas vazias iniciais recebem no máximo uma nova tentativa; uma resposta vazia após executar ferramenta falha claramente sem repetir a ação. Plan continua somente leitura e gravações/comandos exigem aprovação.

O teste `/props` do servidor atual reporta `supports_tools: true`, `supports_reasoning_effort: false` e `supports_preserve_reasoning: false`. O código conserva `reasoning_content` apenas na rodada transitória do loop e não o inclui em sessão persistida. A ausência de suporte declarada impede afirmar que `reasoning_effort` altera o raciocínio do Ornith.
