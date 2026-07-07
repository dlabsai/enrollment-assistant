# Setup

## Prerequisites

- Docker with Compose.
- Chat/eval model credentials.
- Embedding credentials.
- For host-based development: `uv`, Node.js 20+, and `pnpm`.

## Models and embeddings

Tested with OpenAI GPT-5.x models. Uses OpenAI embeddings. Can be configured through the OpenAI API or Azure OpenAI API.

## Start with Docker

```bash
cp .env.example .env
# Edit .env with local credentials.
make demo
```

After the stack starts, build the knowledge-base index from the internal KB Builder, or run:

```bash
make rag
```

Then open the local apps:

| Service | URL |
| --- | --- |
| Backend API | http://localhost:8000/api |
| OpenAPI docs | http://localhost:8000/docs |
| Public widget dev app | http://localhost:5173 |
| Internal app | http://localhost:5174 |

Useful commands:

| Command | Description |
| --- | --- |
| `make demo` | Build and start the Docker Compose stack. |
| `make up` | Same as `make demo`. |
| `make rag` | Rebuild the local knowledge-base index. |
| `make reset` | Recreate the Compose stack. |
| `make down` | Stop the Compose stack. |

## Development

### Backend

```bash
cd backend
uv sync --dev
```

Start Postgres from the repo root, then run migrations and the API:

```bash
./run-db.sh
cd backend
./run-migrations.sh
./run-dev.sh
```

Backend URLs:

- API: http://localhost:8000/api
- OpenAPI docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend
pnpm install
./run-dev-internal.sh  # http://localhost:5174
./run-dev-public.sh    # http://localhost:5173
```

### Checks

```bash
cd backend && ./check.sh
cd frontend && ./check.sh
```

## Environment variables

Backend settings come from process environment variables and, for host-based development, the repo-root `.env` file loaded by the backend. Vite frontend variables are read at dev-server/build time and must use the `VITE_` prefix. Do not commit real secrets; keep `.env.example` public-safe.

### Backend core settings

| Variable | Purpose |
| --- | --- |
| `API_STR` | API path prefix. Defaults to `/api`. |
| `FRONTEND_HOST` | Canonical internal frontend origin used for CORS and browser flows. |
| `ENVIRONMENT` | Runtime environment: `local`, `staging`, or `production`. Also affects secure-cookie defaults. |
| `DEBUG` | Enables debug behavior for local development. |
| `BACKEND_CORS_ORIGINS` | Comma-separated list of allowed browser origins; `FRONTEND_HOST` is also allowed. |
| `PROJECT_NAME` | Internal project label. |

### Databases

| Variable | Purpose |
| --- | --- |
| `POSTGRES_SERVER` | Main PostgreSQL host. Docker Compose overrides this to `db` for containers. |
| `POSTGRES_PORT` | Main PostgreSQL port. |
| `POSTGRES_USER` | Main PostgreSQL user. |
| `POSTGRES_PASSWORD` | Main PostgreSQL password. |
| `POSTGRES_DB` | Main application database name. |
| `PYTEST_POSTGRES_SERVER` | Eval/test PostgreSQL host. |
| `PYTEST_POSTGRES_PORT` | Eval/test PostgreSQL port. |
| `PYTEST_POSTGRES_USER` | Eval/test PostgreSQL user. |
| `PYTEST_POSTGRES_PASSWORD` | Eval/test PostgreSQL password. |
| `PYTEST_POSTGRES_DB` | Eval/test database name; local Compose requires it to end with `_test` and differ from `POSTGRES_DB`. |
| `TELEMETRY_DATABASE_URL` | Optional explicit database URL for telemetry span persistence; falls back to the main database when unset. |

### Model providers and agent defaults

| Variable | Purpose |
| --- | --- |
| `MODELS` | Comma-separated model list exposed in the internal app. |
| `OPENAI_API_KEY` | OpenAI API key for OpenAI-backed model usage. |
| `AZURE_API_KEY_1` | Azure OpenAI resource 1 key. Resource 1 is also used for embeddings. |
| `AZURE_API_BASE_1` | Azure OpenAI resource 1 endpoint. |
| `AZURE_API_VERSION_1` | Azure OpenAI resource 1 API version. |
| `AZURE_API_KEY_2` | Optional Azure OpenAI resource 2 key. |
| `AZURE_API_BASE_2` | Optional Azure OpenAI resource 2 endpoint. |
| `AZURE_API_VERSION_2` | Optional Azure OpenAI resource 2 API version. |
| `AZURE_MODEL_RESOURCE_MAP` | Optional comma-separated deployment-to-resource map, for example `deployment-a:2,deployment-b:1`; unmapped Azure deployments use resource 1. |
| `OPENROUTER_API_KEY` | Existing OpenRouter-compatible code path key; not part of the currently tested provider setup. |
| `LLM_REQUEST_TIMEOUT` | HTTP timeout, in seconds, for model calls. |

| Variable | Purpose |
| --- | --- |
| `CHATBOT_MODEL` | Default chatbot model. |
| `CHATBOT_MODEL_TEMPERATURE` | Chatbot temperature for non-GPT-5-style model settings. |
| `CHATBOT_MODEL_MAX_TOKENS` | Chatbot max-token configuration field; `0` means no explicit configured cap. |
| `INVESTIGATION_MODEL` | Default model for developer investigation chats. |
| `INVESTIGATION_REASONING_EFFORT` | Reasoning effort for investigation chats: `none`, `low`, `medium`, `high`, or `xhigh`. |
| `GUARDRAIL_MODEL` | Default guardrails model. |
| `GUARDRAIL_MODEL_TEMPERATURE` | Guardrails temperature for non-GPT-5-style model settings. |
| `GUARDRAIL_MODEL_MAX_TOKENS` | Guardrails max-token configuration field; `0` means no explicit configured cap. |
| `EVALUATION_MODEL` | Default eval judge model. |
| `EVALUATION_MODEL_TEMPERATURE` | Eval judge temperature for non-GPT-5-style model settings. |
| `EVALUATION_MODEL_MAX_TOKENS` | Eval judge max-token configuration field; `0` means no explicit configured cap. |
| `SUMMARIZER_MODEL` | Default conversation-summary model. |
| `GROUNDING_MODEL` | Default source-grounding model. |
| `GROUNDING_REASONING_EFFORT` | Reasoning effort for grounding: `none`, `low`, `medium`, `high`, or `xhigh`. |

### Guardrails

| Variable | Purpose |
| --- | --- |
| `ENABLE_GUARDRAILS` | Enables the guardrails validation loop. |
| `MAX_GUARDRAILS_RETRIES` | Number of chatbot retries after guardrails reject a draft answer. |
| `GUARDRAILS_BLOCKED_MESSAGE` | Canned message shown when all guardrails retries are rejected. |

### Auth, sessions, and Teams SSO

| Variable | Purpose |
| --- | --- |
| `USER_REGISTRATION_TOKEN` | Registration token for the user group. |
| `ADMIN_REGISTRATION_TOKEN` | Registration token for the admin group. |
| `DEV_REGISTRATION_TOKEN` | Registration token for the dev group. |
| `JWT_SECRET_KEY` | Secret used to sign auth tokens; set a long random value outside local demos. |
| `JWT_ALGORITHM` | JWT signing algorithm. Defaults to `HS256`. |
| `JWT_EXPIRE_MINUTES` | Access-token lifetime in minutes. |
| `ACCESS_TOKEN_COOKIE_NAME` | Access-token cookie name. |
| `ACCESS_TOKEN_COOKIE_PATH` | Access-token cookie path; defaults to `API_STR`. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh-token lifetime in days. |
| `REFRESH_TOKEN_COOKIE_NAME` | Refresh-token cookie name. |
| `REFRESH_TOKEN_COOKIE_PATH` | Refresh-token cookie path; defaults to `${API_STR}/auth`. |
| `REFRESH_TOKEN_COOKIE_SAMESITE` | Refresh-token cookie SameSite value: `lax`, `strict`, or `none`. |
| `REFRESH_TOKEN_COOKIE_SECURE` | Whether refresh-token cookies require HTTPS; defaults to true outside `local`. |
| `TEAMS_SSO_ENABLED` | Enables optional Teams SSO bootstrap. |
| `TEAMS_SSO_TENANT_ID` | Microsoft tenant ID for Teams SSO. |
| `TEAMS_SSO_CLIENT_ID` | Microsoft app/client ID for Teams SSO. |
| `TEAMS_SSO_RESOURCE` | Teams SSO resource URI. |
| `TEAMS_SSO_ALLOWED_AUDIENCES` | Extra comma-separated token audiences accepted for Teams SSO. |

### Scheduler and observability

| Variable | Purpose |
| --- | --- |
| `SCHEDULER` | Enables the standalone scheduler process when truthy. Compose and Azure force web workers to `SCHEDULER=false` and run at most one scheduler process separately. |
| `LANGFUSE_OTEL_ENABLED` | Enables optional Langfuse OTLP trace export. |
| `LANGFUSE_OTEL_ENDPOINT` | Langfuse OTLP endpoint. `/api/public/otel` is normalized to `/api/public/otel/v1/traces`. |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key. |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key. |
| `LANGFUSE_INGESTION_VERSION` | Optional Langfuse ingestion-version header. Defaults to `4`. |
| `LANGFUSE_ENVIRONMENT` | Optional environment label added to exported spans. |

### Frontend and widget settings

| Variable | Purpose |
| --- | --- |
| `VITE_API_URL` | Backend API base URL. Required by both frontend apps. |
| `VITE_ENVIRONMENT` | Optional frontend environment label. |
| `VITE_UNIVERSITY_NAME` | University name shown in frontend copy and page titles. |
| `VITE_UNIVERSITY_WEBSITE_URL` | Base website URL used to derive default policy links. |
| `VITE_ADMISSIONS_PHONE` | Display phone number in public-facing UI copy. |
| `VITE_ADMISSIONS_PHONE_TEL` | Telephone link value; defaults to digits from `VITE_ADMISSIONS_PHONE`. |
| `VITE_PRIVACY_POLICY_URL` | Privacy policy URL; defaults under `VITE_UNIVERSITY_WEBSITE_URL`. |
| `VITE_TERMS_URL` | Terms URL; defaults under `VITE_UNIVERSITY_WEBSITE_URL`. |
| `VITE_CONSENT_COMMUNICATIONS_URL` | Electronic-communications consent URL; defaults under `VITE_UNIVERSITY_WEBSITE_URL`. |
| `VITE_AI_TERMS_URL` | AI terms URL; defaults under `VITE_UNIVERSITY_WEBSITE_URL`. |
| `VITE_PUBLIC_WIDGET_BASE_PATH` | Built public-widget asset base path. Defaults to `/chat-widget/`. |
| `VITE_VISIBLE_BY_DEFAULT` | Public widget visibility toggle; `yes` opens it by default. |
| `VITE_TEAMS_SSO_ENABLED` | Enables Teams SSO behavior in the internal frontend. |
| `VITE_TEAMS_FORCE_MODE` | Forces Teams mode in the internal frontend for testing. |
| `VITE_ENABLE_CHAT_MODEL_SELECTOR` | Shows or hides the internal chat model selector. Defaults to `true`. |
| `VITE_BUNDLE_ANALYZE` | Set to `1` or `true` during build to emit bundle-analysis output. |
| `VITE_REACT_GRAB` | Loads the `react-grab` development helper when set to `true` in dev mode. |

### Docker, deployment, and eval helper variables

| Variable | Purpose |
| --- | --- |
| `DOCKER_IMAGE_BACKEND` | Backend image name used by Docker Compose. |
| `DOCKER_IMAGE_FRONTEND` | Reserved frontend image name from `.env.example`; current local Compose uses Node dev containers instead. |
| `TAG` | Optional Docker image tag used by Compose; defaults to `latest`. |
| `COMPOSE` | Optional Makefile override for the Compose command; defaults to `docker compose`. |
| `COMPOSE_IGNORE_ORPHANS` | Makefile-exported Compose setting; defaults to `1`. |
| `COMPOSE_PROGRESS` | Makefile-exported Compose progress mode; defaults to `quiet`. |
| `AZURE_RESOURCE_GROUP` | Required Azure resource group for `deploy-env.sh` and `deploy-files.sh`. |
| `AZURE_WEBAPP_NAME` | Required Azure Web App name for `deploy-env.sh` and `deploy-files.sh`. |
| `AZURE_POSTGRES_SERVER_NAME` | Optional Azure PostgreSQL flexible-server name for enabling the `vector` extension during `deploy-files.sh`. |
| `WEBAPP_HOST` | Optional deployment-package override for the Azure Web App host; otherwise `deploy-files.sh` asks Azure for the host name. |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | Azure App Service setting used during ZIP deployment. |
| `WEBSITE_HTTPLOGGING_RETENTION_DAYS` | Azure App Service HTTP log retention setting. |
| `PGHOST` | PostgreSQL host for the retrieval-eval CLI direct database connection. |
| `PGUSER` | PostgreSQL user for the retrieval-eval CLI direct database connection. |
| `PGDATABASE` | PostgreSQL database for the retrieval-eval CLI direct database connection. |
| `PGPASSWORD` | Optional PostgreSQL password for the retrieval-eval CLI direct database connection. |
| `PGPORT` | Optional PostgreSQL port for the retrieval-eval CLI direct database connection; defaults to `5432`. |

## Knowledge base content

The default knowledge base uses the included Demo University content. Rebuild it after editing the source content.

## Deployment

For a production-style local build served by the backend:

```bash
./run-prod-local.sh
```

Deployment references:

- [`deployment.md`](deployment.md)
- [`internal-auth-runtime.md`](internal-auth-runtime.md)
- [`teams-admin-deployment-guide.md`](teams-admin-deployment-guide.md)
- [`teams-tab-sso-rollout.md`](teams-tab-sso-rollout.md)
