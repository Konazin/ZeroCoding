# Changelog

## 0.2.0 — 2026-10-17 (fecha o M7)

- Novo mascote Patinhas: anda no lugar enquanto o agente trabalha; o texto que precede uma chamada de ferramenta permanece na tela.
- Streaming ligado por padrão (`streaming_enabled: false` desliga). Devolve `usage`, e argumentos de ferramenta truncados refazem o turno sem streaming.
- Fallback de contagem de tokens recalibrado (erro mediano 6%, p90 12%); a contagem exata do servidor continua sendo o caminho normal.
- Benchmark M7.2 reconciliado: 74/75 sem streaming e 75/75 com streaming. Os verificadores de `run_tests`, `direct_fact` e `destructive_request` foram corrigidos; o harness grava `approval_log` e `answer_excerpt`.
- Pacote: `config/default.yaml` e `skills/` incluídos como recursos; wheel construído e instalado em ambiente limpo com `zc`, `zerocoding` e `zc doctor` funcionando fora do checkout.
- Sessões locais privadas e atômicas (M8).

## 0.1.0

- Primeira versão: TUI, agente com ferramentas, extensões opt-in (M1–M6).
