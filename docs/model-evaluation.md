# Avaliação de modelos locais

Este documento define uma matriz reproduzível para validar chamadas de ferramenta e latência em PCs leves. Ainda não há resultados medidos: os modelos precisam estar instalados no Ollama da máquina de avaliação.

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
