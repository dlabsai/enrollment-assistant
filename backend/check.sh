#!/bin/bash

uv run ruff format
uv run ruff check --fix
uv run ruff format
PYRIGHT_PYTHON_IGNORE_WARNINGS=1 uv run pyright
