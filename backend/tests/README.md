# Testing Guide

This document covers the testing infrastructure for the backend, including how to run tests efficiently with persistent RAG data.

## Quick Start

```bash
# Run all tests (fast - reuses existing RAG data)
uv run pytest

# Run integration/e2e tests only (LLM required)
uv run pytest tests/chat/test_llm_conversation_turn.py -v -s

# Run LLM-as-judge evaluation tests
uv run pytest tests/chat/test_eval_chatbot.py -v -s

# Run guardrails evaluation tests
uv run pytest tests/chat/test_eval_guardrails.py -v -s

# Run specific test cases
uv run pytest tests/chat/test_eval_chatbot.py -v -s -T "greeting_response,accreditation_inquiry"

# Run with repeats for statistical confidence
uv run pytest tests/chat/test_eval_chatbot.py -v -s -R 3 -C 5

# Force rebuild RAG data (expensive - calls embedding API)
uv run pytest --rebuild-rag
```

## Required DB Environment Variables

Set one external DB env set before running tests:

- `PYTEST_POSTGRES_SERVER`
- `PYTEST_POSTGRES_PORT`
- `PYTEST_POSTGRES_USER`
- `PYTEST_POSTGRES_PASSWORD`
- `PYTEST_POSTGRES_DB` (must end with `_test` and differ from `POSTGRES_DB` if set)

`tests/conftest.py` maps these into runtime `POSTGRES_*` and fails fast if missing/unsafe.

For local Docker Compose, the `ensure-test-db` service in `docker-compose.yml`
ensures `PYTEST_POSTGRES_DB` exists on every startup (idempotent).
It also enforces safety checks: DB name must end with `_test` and must differ from `POSTGRES_DB`.

## Pytest Markers

Tests are organized using pytest markers for selective test execution:

| Marker | Description |
|--------|-------------|
| `slow` | Tests that take a long time to run |
| `llm` | Tests that require LLM API calls (Azure OpenAI) |
| `eval` | LLM-as-judge evaluation tests |

```bash
# Run only fast unit tests (exclude LLM tests)
uv run pytest -m "not llm"

# Run only LLM tests
uv run pytest -m llm

# Run only evaluation tests
uv run pytest -m eval

# Run slow tests (includes llm, eval)
uv run pytest -m slow

# Combine markers (e.g., slow but not eval)
uv run pytest -m "slow and not eval"
```

## Test Categories

### Unit Tests
Standard unit tests that don't require external services or databases.

### Integration Tests (E2E)
End-to-end tests that call real LLMs and use a real PostgreSQL database with RAG data.

Located in: `tests/chat/test_llm_conversation_turn.py`

### LLM-as-Judge Evaluation Tests

These tests use an LLM judge to evaluate agent responses against defined criteria. They use a custom evaluation library (`app/evals`) that supports:
- **Repeats**: Run each test case multiple times for statistical confidence
- **Parallel execution**: Run cases concurrently with configurable concurrency
- **Detailed reports**: Pass rates, durations, and per-assertion statistics
- **Test case filtering**: Run specific test cases by ID

| Test File | Component Tested | Description |
|-----------|-----------------|-------------|
| `test_eval_chatbot.py` | Full chatbot pipeline | Tests the complete path: retrieval-capable chatbot → guardrails |
| `test_eval_guardrails.py` | Guardrails agent (isolated) | Tests if guardrails correctly identifies valid/invalid responses |

**Common Options:**
- `-R N` / `--repeat=N`: Number of times to repeat each test case (default: 1)
- `-C N` / `--max-concurrency=N`: Maximum concurrent LLM calls (default: 5)
- `-T IDs` / `--test-cases=IDs`: Comma-separated list of test case IDs to run
- `-P N` / `--pass-threshold=N`: Minimum pass rate threshold (default: 0.9 = 90%)
- `--chatbot-model=MODEL`: Override chatbot model for eval tests
- `--guardrail-model=MODEL`: Override guardrails model for eval tests
- `--evaluation-model=MODEL`: Override LLM-judge/evaluation model for eval tests

```bash
# Run full pipeline tests with 3 repeats
uv run pytest tests/chat/test_eval_chatbot.py -v -s -R 3 -C 5

# Run guardrails tests for specific violations
uv run pytest tests/chat/test_eval_guardrails.py -v -s -T "dollar_amounts_violation,free_word_violation"

# Run with lower pass threshold (80%)
uv run pytest tests/chat/test_eval_chatbot.py -v -s -R 5 -P 0.8

# Run specific case with explicit per-role model overrides
uv run pytest tests/chat/test_eval_chatbot.py -v -s -T "no_blog_urls" -R 20 -C 10 \
  --chatbot-model azure/gpt-5.4 \
  --guardrail-model azure/gpt-5.4 \
  --evaluation-model azure/gpt-5.4
```

**DB routing behavior:**
- All suites use the same external DB env set: `PYTEST_POSTGRES_*`.

## Chatbot Flow Architecture

```
CHATBOT FLOW:
User Input --> Retrieval-capable Chatbot Agent --> Guardrails --> Response
                         |                         |
                         |                         |
                    RAG/lookup tools:        (retry chatbot+guardrails if fails,
                    - retrieve_documents      up to 2 retries by default)
                    - find_document_titles
                    - find_document_chunks
                    - list_catalog_programs
                    - list_website_pages

ISOLATED COMPONENT TESTS:
┌─────────────────────────────────────────────────────────────────┐
│ test_eval_guardrails.py                                         │
│ Tests guardrails agent in isolation:                            │
│ - Does it catch rule violations ($ amounts, "free", etc.)?      │
│ - Does it correctly pass valid responses?                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ test_eval_chatbot.py                                            │
│ Tests full pipeline end-to-end:                                 │
│ - Does the final response follow guidelines?                    │
│ - Is it grounded in RAG data?                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Persistent RAG Data

RAG data population is expensive because it creates embeddings via Azure OpenAI API.
Data is persisted in the external test database selected via `PYTEST_POSTGRES_*`, so repeated
runs reuse existing RAG data unless `--rebuild-rag` is set.

## Troubleshooting

### Tests fail at startup with missing DB env vars
Set all required `PYTEST_POSTGRES_*` vars before running pytest.

### Need to update RAG data after source changes
```bash
uv run pytest --rebuild-rag tests/chat/test_llm_conversation_turn.py
```

### No RAG source data available
If RAG source data files are missing, see the [RAG Data Pipeline documentation](../app/rag/README.md).
