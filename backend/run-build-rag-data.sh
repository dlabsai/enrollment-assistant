#!/bin/bash

set -e

uv run -m app.rag.cli "$@"
