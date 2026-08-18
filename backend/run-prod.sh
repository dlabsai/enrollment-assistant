#!/bin/bash

WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}" uv run fastapi run app/main.py
