SHELL := /bin/bash

export UID := $(shell id -u)
export GID := $(shell id -g)
export COMPOSE_IGNORE_ORPHANS ?= 1
export COMPOSE_PROGRESS ?= quiet

COMPOSE ?= docker compose

.PHONY: up demo rag reset down

up:
	$(COMPOSE) up -d --build

demo: up

rag:
	cd backend && uv run -m app.rag.cli sync

reset:
	$(COMPOSE) down
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down
