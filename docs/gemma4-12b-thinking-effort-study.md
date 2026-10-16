# Gemma 4 12B: thinking, effort, latency and memory

## Goal

Measure whether the locally installed `gemma4:12b` is a practical alternative to the Qwen3.5-9B candidate on the same five ZeroCoding workflows. This is a temporary benchmark profile; it does not change the product default or configuration.

Gemma 4 exposes thinking as an on/off control and supports native function calling. Google recommends `temperature=1.0`, `top_p=0.95`, and `top_k=64`; Gemma 4 does not expose native Low/Medium/High thinking levels. The runner therefore keeps the prior study's ZeroCoding effort budgets and switches thinking through Ollama's boolean `think` field. [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4), [thinking controls](https://ai.google.dev/gemma/docs/capabilities/thinking), [function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4).

## Protocol

- 90 responses: project fact, tool read, edit and unit test, Plan Mode, and denied write × thinking off/on × Low/Medium/High agent budget × three repetitions.
- Gemma-specific sampling: temperature 1.0, `top_p=0.95`, `top_k=64`, presence penalty 0, repetition penalty 1.0. Seeds are paired by repetition.
- Same ZeroCoding agent, tasks, fixtures, system prompts, context (`num_ctx=6144`), input limit (4096 tokens), output/tool budgets, and approval rules as the Qwen3.5-9B study.
- The only model-specific adaptation is its recommended sampling profile and native boolean thinking control. Effort levels remain agent budgets (512/1024/2048 output tokens; 3/6/8 tool rounds), not native Gemma levels.
- The temporary fixture permits only the target edit and fixed unit-test command. Plan Mode and denied-write cases must not alter files or run commands.
- Each trial samples system RAM available, Ollama runner RSS, device-wide VRAM and GPU busy time, and Ollama's per-model runtime and VRAM memory fields. The preflight records exact model tag size/digest and checks thinking and native tool calling.
- The model is already installed. The runner refuses to download an absent model.

## Run / resume

```bash
uv run python scripts/gemma4_12b_thinking_effort_study.py plan
uv run python scripts/gemma4_12b_thinking_effort_study.py run
uv run python scripts/gemma4_12b_thinking_effort_study.py run --resume-run-dir .zerocoding/studies/m2/gemma4-12b-thinking-effort/runs/<run-id>
```

Detailed traces and host samples remain in the ignored `.zerocoding/studies/m2/gemma4-12b-thinking-effort/` directory. The aggregate is saved in `docs/gemma4-12b-thinking-effort-results.json`.

## Comparison limits

The Qwen baseline used its recommended coding sampling profile (`temperature=0.6`, `top_p=0.95`, `top_k=20`), while Gemma uses Google's recommended sampler. Tasks, budgets, context, and harness are held constant, but this is a candidate-level comparison under model-specific settings, not a strict experiment isolating model weights. Three repetitions per condition provide directional evidence only.

The Qwen baseline reported 6,594,474,711 bytes on disk, with a device-wide peak of 7,070,736,384 bytes VRAM and a minimum of 6,794,338,304 bytes system RAM available. It did not capture Ollama runner RSS or the model-specific `/api/ps` VRAM field. The Gemma run records both additional process/model metrics; any direct comparisons will label these measurement differences.

## Results

Run `20261012T230738Z-c4d4b4` completed on 12 October 2026 in 31m 7s using Ollama 0.40.0. It used the locally installed 11.9B-parameter `gemma4:12b`, Q4_K_M, digest `4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`. No model was downloaded.

### Overall against Qwen3.5-9B

| Model / mode | Objective pass | Final answer present | Median latency | P95 latency | Median generated tokens |
|---|---:|---:|---:|---:|---:|
| Gemma 4 12B, thinking off | 38/45 (84.4%) | 45/45 | 16.37 s | 23.48 s | 88 |
| Qwen3.5 9B, thinking off | 42/45 (93.3%) | 45/45 | 13.12 s | 24.66 s | 96 |
| Gemma 4 12B, thinking on | 42/45 (93.3%) | 45/45 | 29.12 s | 42.28 s | 194 |
| Qwen3.5 9B, thinking on | 27/45 (60.0%) | 24/45 | 22.54 s | 36.90 s | 219 |

Across all 90 cases, Gemma passed 80 (88.9%) and Qwen passed 69 (76.7%). Both safety gates passed. For Gemma, enabling thinking raised the objective score by 8.9 percentage points and increased median latency by 78% over Gemma's own thinking-off mode. Qwen showed the opposite quality pattern: thinking off was its strongest mode, while thinking on produced empty final answers in 21/45 cases.

| Workflow | Gemma off | Gemma on | Qwen off | Qwen on |
|---|---:|---:|---:|---:|
| Project fact | 9/9 | 9/9 | 6/9 | 6/9 |
| Read symbol with tools | 3/9 | 6/9 | 9/9 | 9/9 |
| Edit and run test | 8/9 | 9/9 | 9/9 | 6/9 |
| Plan Mode | 9/9 | 9/9 | 9/9 | 0/9 |
| Denied write | 9/9 | 9/9 | 9/9 | 6/9 |

Gemma's ten failed cases were specific: nine final answers omitted the symbol name `format_total` after successfully using the read tools, and one Low/thinking-off edit applied the requested value but did not run the fixed test command. All 45 Gemma thinking-on trials returned a nonempty final answer, including all Plan Mode cases. No Plan Mode or denied-write case changed a file or ran a command.

The preflight arithmetic probe capped generation at 128 tokens: thinking off returned an answer; thinking on used the cap without a final answer. That short cap was below what this Gemma configuration needed for a final answer in that probe. The main matrix used the agreed effort budgets and returned nonempty final answers in all 45 thinking-on cases. A separate native-tool preflight successfully produced the requested `confirm_read` call.

### Effort budgets

| Thinking | Agent budget | Gemma passes / 15 | Gemma median latency | Qwen passes / 15 |
|---|---|---:|---:|---:|
| Off | Low | 12/15 | 17.09 s | 14/15 |
| Off | Medium | 13/15 | 14.90 s | 14/15 |
| Off | High | 13/15 | 17.29 s | 14/15 |
| On | Low | 14/15 | 29.76 s | 9/15 |
| On | Medium | 14/15 | 27.12 s | 9/15 |
| On | High | 14/15 | 29.31 s | 9/15 |

The Low/Medium/High budgets are external ZeroCoding limits, not Gemma controls. Within the nine cells, quality did not improve steadily with the larger token/tool budgets. The meaningful difference for Gemma was whether native thinking was on; the user should not interpret the budgets as Gemma's native reasoning levels.

### Physical footprint on this PC

The Gemma tag reports 7,556,508,396 bytes on disk. The Qwen alias loaded by the memory calibration reports 6,603,314,868 bytes, making Gemma's package 953,193,528 bytes, or 14.4%, larger. Ollama reports tag `size` as disk bytes; `/api/ps` reports loaded model size and `size_vram` for the part placed in VRAM. [Ollama API](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml).

| Measurement | Qwen3.5-9B | Gemma 4 12B |
|---|---:|---:|
| Installed tag size on disk | 6.603 GB | 7.557 GB |
| Ollama loaded-model size (`/api/ps`) | 6.386 GB* | 8.122 GB |
| Model-attributed VRAM (`size_vram`) | 5.454 GB* | 6.001 GB |
| Ollama runner peak RSS | 5.982 GB* | 8.164 GB |
| Device-wide VRAM peak during 90-case matrix | 7.071 GB | 7.030 GB |
| Minimum system RAM available during 90-case matrix | 6.794 GB | 3.515 GB |

*Qwen's model-specific values come from a separate, short memory calibration after unloading Gemma. It used the same 6144 context and Qwen sampling profile, with thinking off; it was not a second Qwen matrix. That one request took 24.03 s because loading the Qwen model took 23.66 s. The old Qwen matrix sampler did not recognize Ollama's `llama-server` process, so its RSS and model-specific VRAM fields were unavailable. The Gemma values are peaks collected throughout its matrix. These differing scopes are why the table reports the calibration source rather than treating the RSS and `/api/ps` figures as a strictly controlled head-to-head.

Ollama also returns two exact-name `qwen3.5:9b` entries locally: digest `2e16a80f…` with runner `ggml`, and digest `c97eb11d…` with runner `llamacpp`. The prior Qwen matrix recorded the first `/api/tags` entry. `/api/show` resolves the name to the `llamacpp` runner, and both current Modelfiles point to the same two on-disk weight blobs (6,603,303,264 bytes total); the memory calibration's live `ollama ps` ID was `c97eb11d70b1`. The old matrix did not capture the live `/api/ps` ID, so exact runtime digest identity for that run is unverified, although the inspected alias definitions share their weight files. The Qwen runner now selects the `/api/tags` entry matching `/api/show`'s runner and records all duplicate name matches.

The two 90-case runs had almost the same device-wide VRAM peak, but Gemma's model-specific allocation was larger: 6.001 GB against Qwen's calibrated 5.454 GB. Gemma's loaded allocation was 8.122 GB, so Ollama placed about 74% on GPU and the rest outside VRAM (the CLI showed 26% CPU / 74% GPU). Its runner peaked at 8.164 GB RSS and system RAM available fell to 3.515 GB. Qwen's short calibration placed about 85% of its loaded allocation on GPU, with a 5.982 GB runner peak; its matrix had 6.794 GB minimum available RAM. `MemAvailable` is system-wide, and these were separate runs, so that RAM difference is indicative rather than an exact attribution to model weights alone.

The Gemma footprint is feasible on this 16 GB RAM / 8 GB VRAM PC at context 6144, but it leaves materially less RAM headroom and relies more on CPU offload. The 12B artifact is 14.4% larger on disk, its measured runner RSS peak was 36.5% larger than the Qwen memory calibration, and the Gemma matrix was 25–29% slower at the same thinking state. Ollama's Gemma 4 guidance explicitly warns that system RAM offload can slow responses when VRAM is insufficient. [Ollama Gemma 4 guidance](https://github.com/ollama/ollama/blob/main/docs/quickstart.mdx).

### Engineering decision

Keep both as candidates; do not replace the lightweight default with Gemma 4 12B based on this matrix alone. Qwen with thinking off remains faster and better at the tool-read fixture. Gemma with thinking on produced more reliable final answers, succeeded in Plan Mode and denied-write cases where Qwen thinking-on failed, and scored higher overall; it paid for that with 29.1 s median latency and substantial RAM use. On this PC, Gemma fits better as a deliberate quality-oriented option than as the always-on default.

The most useful harness follow-ups are model-specific thinking/sampling profiles, a final-answer check that verifies the requested symbol was named, and a bounded response recovery when the model used tools but omitted the concrete result. The matrix also confirms that one shared Low/Medium/High token budget is not a substitute for a model-native thinking control.

### Artifacts

- Aggregated result: [`gemma4-12b-thinking-effort-results.json`](gemma4-12b-thinking-effort-results.json)
- Full matrix traces and memory samples: `.zerocoding/studies/m2/gemma4-12b-thinking-effort/runs/20261012T230738Z-c4d4b4/`
- Qwen memory calibration: `.zerocoding/studies/m2/gemma4-12b-thinking-effort/qwen35-memory-calibration.json`
