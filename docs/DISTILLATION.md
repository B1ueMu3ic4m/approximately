# Distillation recipes — judge → small local model

The LLM judge classifies failures with a frontier model by default.
You don't have to keep paying that bill: `approximately distill` exports
labeled trajectories, you fine-tune a small model (1–7B is enough for
the mechanical modes), serve it behind any OpenAI-compatible endpoint,
and point `--judge-model` at it. `approximately benchmark` closes the
loop by measuring exactly what you lost (and kept) per MAST mode.

## The loop

```
# 1. export from your own store (rules labeler — free, no API)
approximately export-dataset sft.jsonl --limit 2000

# 2a. or teacher-labeled (strong judge — better labels, costs API)
approximately export-dataset sft.jsonl --limit 2000 --teacher gpt-4o-mini

# 2. fine-tune with your stack (recipes below)

# 3. serve an OpenAI-compatible endpoint

# 4. measure what the small model kept
approximately benchmark mast-data.jsonl --judge --judge-model my-local-model \
    --html leaderboard.html
```

`export-dataset` writes plain JSONL (`{"task", "steps", "label"}`);
`--teacher` labels with the judge instead of the rule detectors. The
`local` judge preset pairs with distilled models: a compact ids-only
prompt (no taxonomy prose), which is what small models classify best.

## Recipes per serving stack

### Ollama (laptop, zero infra)

1. Fine-tune upstream (LoRA via [ Unsloth / Axolotl / LLaMA-Factory ] on
   `sft.jsonl`), export GGUF.
2. Import a `Modelfile`:

   ```
   FROM ./distilled-7b-q4.gguf
   PARAMETER temperature 0
   ```

3. `ollama create approximately-judge -f Modelfile && ollama serve`
4. `approximately attribute <trace> --judge --judge-model approximately-judge`

Ollama speaks the OpenAI protocol at `http://localhost:11434/v1`, so no
code changes are needed — set `OPENAI_BASE_URL` and every judge call
hits the local model.

### llama.cpp

Same GGUF as above; run `llama-server -m distilled-7b-q4.gguf --port 8080`.
The server exposes `/v1/chat/completions`; use `OPENAI_BASE_URL`.
Keep `temperature 0` (classification, not generation) and prefer Q8 or
Q6 quantization — Q4+ measurably degrades the rare modes (FM-1.1/1.2).

### vLLM (production, many agents)

LoRA adapter straight from training, no GGUF step:

```bash
vllm serve base-7b --enable-lora --lora-modules judge=./lora-adapter \
    --port 8000
```

`model=judge` from `--judge-model` then routes to the adapter. vLLM is
the right choice when attribution runs continuously (CI + dashboards):
batched throughput absorbs the per-trace judge calls.

### HuggingFace TGI

`text-generation-launcher --model-id <your-finetune> --port 8080` — the
Messages API is OpenAI-compatible (`/v1/chat/completions`). Set
`--max-input-length` generously: `_compact_trace` keeps prompts small,
but 100+ step traces still need room.

### OpenAI fine-tunes (hosted, no serving)

`openai api fine_tuning.jobs.create -t sft.jsonl -m gpt-4o-mini` and set
`--judge-model ft:gpt-4o-mini:...`. This keeps the API bill but drops it
~2-3x vs frontier prompts, and needs zero infra. Good first step before
committing to local serving.

## What to expect (honest numbers)

- Modes with structural evidence (FM-1.3 repeats, FM-3.2 missing
  verification, FM-3.1 premature termination) classify nearly as well
  with a 7B as with a frontier judge — the signal is mechanical.
- Modes needing reading comprehension (FM-2.6 reasoning-action mismatch,
  FM-1.1 spec violations) lose the most; expect macro-F1 to drop more
  than accuracy (rare modes get rare).
- **Keep the rule detectors on regardless** — they are free, and the
  fusion layer treats the judge as one evidence source, not the truth.
  A distilled judge that's 85% as good as frontier still moves the
  fused verdict in the right direction most of the time.

Measure, don't assume: `benchmark --html leaderboard.html` per mode is
the acceptance test for a distilled model before it replaces the
frontier judge in your pipeline.
