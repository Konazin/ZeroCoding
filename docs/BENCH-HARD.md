# Benchmark difícil (multi-arquivo)

As 15 tarefas do M7.2 saturaram (98,7% e 100% com o Ornith), então não mostram mais ganho. A suíte `--suite hard` tem 8 tarefas em mini-repositórios maiores, com o mesmo critério mecânico (rodar os testes, conferir arquivos). Cada tarefa tem uma solução de referência em `scripts/bench_hard_cases.py`; `tests/test_bench_hard_cases.py` prova que o verificador aceita a solução, rejeita o estado inicial e rejeita quem edita os testes para passar.

```bash
uv run python scripts/m7_bench.py --suite hard --label <modelo> --model <alias> --base-url http://127.0.0.1:8080/v1 --repetitions 3
```

## Baseline: Qwen 3.5 4B Q6_K (llama.cpp, n_ctx 8192), 3 repetições

Resultado: **17/24 (70,8%)**, pico de RSS 9,2 GB (máquina compartilhada, não é medida limpa). Dados: [`m9-qwen35-4b-q6k-hard-benchmark.json`](m9-qwen35-4b-q6k-hard-benchmark.json).

| Tarefa | Passou | Mediana |
|---|---|---|
| h_edit_inside_long_file | 3/3 | 24 s |
| h_cross_file_question | 3/3 | 23 s |
| h_feature_with_test | 3/3 | 54 s |
| h_run_tests_then_fix | 3/3 | 36 s |
| h_rename_class_5_files | 2/3 | 92 s |
| h_extract_function_module | 2/3 | 93 s |
| h_root_cause_dependency | 1/3 | 45 s |
| h_two_bugs_two_modules | 0/3 | 85 s |

Falhas inspecionadas: em `h_root_cause_dependency` o modelo troca `RATE = 8` por `0.08` sem rodar os testes e `apply_tax` continua errada; em `h_two_bugs_two_modules` ele corrige `title_case` com uma regra errada (palavras com menos de 4 letras ficam minúsculas, então "war" também). São erros do modelo, não do verificador.

## Limites

- Só um modelo foi medido; o Ornith 1.5 9B ainda não rodou esta suíte e é o baseline que decide se o M7.5 reabre.
- Três repetições dão faixa, não intervalo de confiança; `h_rename_class_5_files` variou entre rodadas.
- Os comandos de teste são aprovados automaticamente nas tarefas; outros comandos (pytest) são negados.
