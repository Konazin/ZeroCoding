# Avaliação do `zc init`

## Baseline e máquina observada

O baseline permanece `qwen2.5-coder:7b`; a avaliação CLI registrada abaixo foi 2/5, então ele continua como referência reproduzível e ainda não atingiu a meta. `qwen3.5:4b` fica como desafiante para medir depois, sem download automático. Nesta execução, `ollama list` não conseguiu consultar `127.0.0.1:11434` por restrição de socket, portanto não foi possível confirmar modelos instalados nem repetir a avaliação.

O ambiente expôs AMD Ryzen 5 4600G (6 núcleos/12 threads), 15 GiB de RAM visível e nenhum `/dev/dri` ou `nvidia-smi`. Node.js 26.1.0 e npm 11.13.0 estão disponíveis. A ausência de dispositivo GPU é uma observação deste ambiente isolado, não uma afirmação sobre o hardware físico completo.

Para `full-access`, bubblewrap precisa criar um namespace de rede isolado. O smoke check sem rede foi bloqueado pelo ambiente (`NETLINK_ROUTE: Operation not permitted`); por isso esse modo permanece indisponível aqui. O sandbox executou `/usr/bin/true` com o namespace de rede compartilhado, mas essa execução não valida o requisito de isolamento de rede.

## Protocolo

Baseline local: `qwen2.5-coder:7b` pelo Ollama, com sessões limpas em diretórios temporários. O teste conta como aprovado somente quando o modelo altera o módulo e o teste do scaffold, os testes específicos passam e o `pyproject.toml` continua intacto. Passar apenas o teste vazio do scaffold não conta.

O fluxo pediu aprovação antes de gravar e antes de executar testes. Quando a verificação falhou, o ZeroCoding tentou uma correção e pediu nova aprovação para repetir o comando. Nenhuma dependência foi instalada durante esta avaliação e nenhuma configuração do usuário foi salva.

## CLI

| Descrição | Código e teste alterados | Testes específicos | Saída do provider | Chamadas de ferramenta | Duração do agente | Resultado |
|---|---:|---:|---:|---:|---:|---|
| Saudação com opção `--uppercase` | Sim | Passaram | 491 tokens | 2 | 29,2 s ponta a ponta | Aprovado |
| Calculadora com quatro operações | Sim | Passaram | 779 tokens | 2 | Não capturada | Aprovado |
| Contagem de palavras e top N | Sim | Falharam: string de teste com erro de sintaxe | 1.071 tokens | 1 + reparo | 35,7 s na geração | Reprovado |
| Conversor Celsius/Fahrenheit | Sim | Falharam após reparo: argumentos inválidos produziram `SystemExit` incompatível com os testes | 1.371 tokens | 1 + reparo | 53,5 s na geração | Reprovado |
| Gerador de slug | Sim | Falharam após reparo: o teste importou um nome ausente do módulo | 724 tokens | 2 + reparo | 40,9 s na geração | Reprovado |

O scaffold CLI passou seus testes-base quando ficou sem alterações, mas esses casos foram classificados como não implementados e não entram na taxa de sucesso. O `pyproject.toml` foi preservado nos cinco casos.

**Resultado CLI: 2/5**, abaixo da meta inicial de 4/5. A estrutura `src/`, a aprovação e a execução de testes funcionam. O modelo ainda falha em manter código e testes consistentes e pode emitir código sintaticamente inválido. O reparo único não resolveu três falhas.

### Iteração de prompt e contexto

Depois do baseline, o prompt passou a exigir imports pelo módulo real, helpers com parâmetros simples, testes apenas para requisitos pedidos e chamadas sequenciais. O módulo e o teste do scaffold também entram explicitamente no contexto, atualizado antes de retry e reparo. A suíte automatizada continua verde.

Um smoke check adicional de saudação não foi contado no 2/5: o modelo criou um teste para nome vazio, comportamento que a descrição não exigia; o primeiro teste falhou porque a função pura não lançava `ValueError`. O reparo moveu a validação para `main`, sem corrigir a função chamada pelo teste. Reforcei a instrução para validar dentro do helper, mas a repetição ainda falhou. Isso reforça que a meta de 4/5 ainda não foi atingida; prompt e contexto explícito, por si só, não tornaram o modelo consistente.

## API

FastAPI, pytest e httpx não estão instalados no ambiente atual. O scaffold declara FastAPI e as dependências de teste; o ZeroCoding informa a verificação como não realizada e oferece instalação em `.venv` após aprovação separada. Os cinco casos API ainda não foram executados nem contabilizados.

## Próximos critérios

- Melhorar geração e reparo para que imports, assinaturas e testes permaneçam consistentes dentro do limite de 1.024 tokens.
- Repetir cinco casos CLI fixos até atingir 4/5 com testes específicos aprovados.
- Avaliar cinco casos API após a aprovação da instalação temporária e, depois, testar modelos locais de 3–4B.
