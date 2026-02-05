# RAG Evaluation (Local)

This repo includes a lightweight, local evaluation harness for RAG retrieval
quality. It can optionally report runs to LangSmith when API keys are present.

## What it measures (LLM-based only)
- Retrieval relevance: do the retrieved chunks contain information relevant to the question?
- Answer relevance: does the answer address the question?
- Groundedness: is the answer supported by retrieved chunks?

## Tracing
The eval runner is annotated with `@traceable` and wraps OpenAI calls with
`wrap_openai` so each retrieval + generation + judge step is traced in LangSmith
when `LANGSMITH_TRACING=true`.

## Required API Keys
All evaluations require:
- `OPENAI_API_KEY`

With LangSmith logging:
- `LANGSMITH_API_KEY`
- `LANGSMITH_TRACING=true`
- `LANGSMITH_PROJECT=opsrelay-rag-evals`
- `LANGSMITH_ENDPOINT=https://api.smith.langchain.com` (optional)

## Run locally (LLM-based)
```bash
python backend/tools/run_rag_eval.py \
  --dataset datasets/evals/rag_eval_cases.jsonl \
  --limit 5
```

## Optional flags
- `--fail-under 0.6` exits nonzero if any score falls below the threshold.
- `--debug` prints retrieved chunks and scores per query.

## Optional: load private .env
Create a `.env` file at the repo root (it is ignored by git):
```
LANGSMITH_API_KEY=...
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=opsrelay-rag-evals
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
OPENAI_API_KEY=...
OPENAI_EVAL_MODEL=gpt-5.2
OPENAI_RAG_MODEL=gpt-5.2
```

Then run:
```bash
python backend/tools/run_rag_eval.py \
  --dataset datasets/evals/rag_eval_cases.jsonl \
  --limit 5
```

## Optional: LangSmith logging
```bash
export LANGCHAIN_API_KEY="..."
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_PROJECT="opsrelay-rag-evals"

python backend/tools/run_rag_eval.py \
  --dataset datasets/evals/rag_eval_cases.jsonl \
  --limit 5 \
  --log-langsmith
```

## Dataset format
Each line is JSON with fields:
- `id`: unique identifier
- `question`: user query
- `expected_source_document`: expected runbook filename
- `expected_contains`: short phrase expected in a relevant chunk
- `expected_answer_contains`: phrase expected in a good answer (optional)
- `gold_answer`: reference answer for correctness scoring (optional)
