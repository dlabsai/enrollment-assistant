# Inspecting Demo RAG data files

This guide covers local inspection and validation of the tracked Demo University Markdown corpus and its generated JSON. It does not replace the pipeline and corpus design documentation.

Run commands from `backend/`:

```bash
cd backend
```

## Ownership and file map

The editable source of truth is the Markdown corpus under `app/rag/demo_corpus/`:

```text
app/rag/demo_corpus/
  website/pages/*.md
  website/programs/*.md
  catalog/pages/*.md
  catalog/programs/*.md
  catalog/courses/*.md
  training_materials/**/*.md
```

`uv run -m app.rag.demo_corpus.generate` deterministically writes the normalized build inputs:

```text
app/rag/data/website_pages.json
app/rag/data/website_programs.json
app/rag/data/catalog_pages.json
app/rag/data/catalog_programs.json
app/rag/data/catalog_courses.json
app/rag/data/training_materials.json
```

Both the Markdown sources and generated JSON are tracked and packaged. Edit Markdown or generator logic, regenerate JSON, and review both sides of the diff. Do not hand-edit generated JSON. PostgreSQL `document` and `document_content_chunk` rows are the runtime search index after a successful build; they are not source files.

Check tracked ownership before working on a path:

```bash
git ls-files app/rag/demo_corpus app/rag/data
```

## Inspect Markdown sources

List the corpus deterministically:

```bash
find app/rag/demo_corpus -type f -name '*.md' | sort
```

Search source content and front matter without opening every file:

```bash
rg -n -i 'licensure|transfer credit' app/rag/demo_corpus
rg -n '^title:|^url:|^source_updated_at:' app/rag/demo_corpus | head -40
```

Inspect one document:

```bash
less app/rag/demo_corpus/catalog/pages/academic-policies.md
```

## Inspect JSON without dumping entire files

Start with collection shape, count, and representative keys:

```bash
jq '{type: type, count: length, first_keys: ((.[0] // {}) | keys)}' \
  app/rag/data/website_pages.json
```

List a small title/URL sample:

```bash
jq -r '.[0:10][] | [.id, .title, .url] | @tsv' \
  app/rag/data/catalog_courses.json
```

Search titles safely with a bound argument:

```bash
jq --arg query 'business' \
  '[.[] | select(.title | ascii_downcase | contains($query)) | {id, title, url}]' \
  app/rag/data/website_programs.json
```

Read one normalized Markdown body:

```bash
jq -r '.[] | select(.id == "catalog-page-academic-policies") | .markdown_content' \
  app/rag/data/catalog_pages.json | less
```

Count training materials by source extension:

```bash
jq -r '
  sort_by(.file_extension)
  | group_by(.file_extension)[]
  | "\(.[0].file_extension)\t\(length)"
' app/rag/data/training_materials.json
```

Find records missing required display content:

```bash
jq '[
  .[]
  | select((.title // "") == "" or (.url // "") == "" or (.markdown_content // "") == "")
  | {id, title, url}
] | {count: length, sample: .[0:20]}' app/rag/data/website_pages.json
```

Validate syntax without printing file contents:

```bash
for file in app/rag/data/*.json; do jq empty "$file" || exit; done
```

## Validate with application models

Use the same Pydantic models loaded by the RAG build:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

from app.rag.models import (
    CatalogCourse,
    CatalogPage,
    CatalogProgram,
    TrainingMaterial,
    WebsitePage,
    WebsiteProgram,
)

checks = {
    "app/rag/data/website_pages.json": WebsitePage,
    "app/rag/data/website_programs.json": WebsiteProgram,
    "app/rag/data/catalog_pages.json": CatalogPage,
    "app/rag/data/catalog_programs.json": CatalogProgram,
    "app/rag/data/catalog_courses.json": CatalogCourse,
    "app/rag/data/training_materials.json": TrainingMaterial,
}

for filename, model in checks.items():
    rows = json.loads(Path(filename).read_text())
    for row in rows:
        model.model_validate(row)
    print(f"OK   {filename}: {len(rows)} records")
PY
```

## Regenerate and compare

Regenerate only the deterministic source JSON when editing corpus content:

```bash
uv run -m app.rag.demo_corpus.generate
git diff --stat -- app/rag/demo_corpus app/rag/data
git diff -- app/rag/demo_corpus app/rag/data
```

For ordering-insensitive investigation, keep snapshots under ignored `tmp/` and normalize by ID:

```bash
mkdir -p tmp/data-audit
cp app/rag/data/catalog_courses.json tmp/data-audit/catalog-courses.before.json

# Make the source/generator change, then regenerate.
uv run -m app.rag.demo_corpus.generate

jq -S 'sort_by(.id)' tmp/data-audit/catalog-courses.before.json \
  > tmp/data-audit/catalog-courses.before.sorted.json
jq -S 'sort_by(.id)' app/rag/data/catalog_courses.json \
  > tmp/data-audit/catalog-courses.after.sorted.json
diff -u tmp/data-audit/catalog-courses.{before,after}.sorted.json | less
```

A formatting- or ordering-only rewrite is not automatically meaningful. Review stable IDs, source keys, titles, URLs, Markdown, and source timestamps.

Use the shared orchestrator when validating the complete database pipeline:

```bash
uv run -m app.rag.cli sync
```

## Canonical references

- [RAG pipeline overview](../app/rag/README.md)
- [Demo corpus contract](../../lode/rag/demo-corpus.md)
- [RAG summary](../../lode/rag/summary.md)
- [Training-material contract](../../lode/rag/training-materials.md)
- [Testing guide](../tests/README.md)
