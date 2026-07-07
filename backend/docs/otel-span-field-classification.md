# OTel Span Field Classification

This note documents which `OtelSpan` fields in `backend/app/models.py` are:

1. standard OpenTelemetry trace data model fields,
2. standard OpenTelemetry semantic-convention attributes promoted into dedicated DB columns,
3. custom/vendor-specific fields, or
4. derived convenience fields.

It is based on the current extraction logic in `backend/app/otel.py`, especially `_span_to_payload(...)`.

## Source files reviewed

- `backend/app/models.py`
- `backend/app/otel.py`

## Official references

### OpenTelemetry core trace model
- Trace API: <https://opentelemetry.io/docs/specs/otel/trace/api/>
- Traces concept: <https://opentelemetry.io/docs/concepts/signals/traces/>
- Resource spec: <https://opentelemetry.io/docs/specs/otel/resource/>
- Instrumentation scope concept: <https://opentelemetry.io/docs/concepts/instrumentation-scope/>
- Instrumentation scope spec: <https://opentelemetry.io/docs/specs/otel/common/instrumentation-scope/>

### OpenTelemetry semantic conventions
- Semantic conventions overview: <https://opentelemetry.io/docs/specs/otel/semantic-conventions/>
- `server.address`: <https://opentelemetry.io/docs/specs/semconv/registry/attributes/server/>
- GenAI overview: <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- GenAI spans: <https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/>
- GenAI metrics: <https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/>
- Semantic conventions repository: <https://github.com/open-telemetry/semantic-conventions>

## `OtelSpan` column classification

| Column | Source in payload builder | Classification | Notes |
|---|---|---|---|
| `trace_id` | `span.context.trace_id` | Standard OTel | Core span identity |
| `span_id` | `span.context.span_id` | Standard OTel | Core span identity |
| `parent_span_id` | `span.parent.span_id` | Standard OTel | Parent link in trace tree |
| `name` | formatted span name | Standard OTel field, vendor-influenced formatting | Final stored value may be rewritten using Logfire message attributes |
| `kind` | `span.kind.name` | Standard OTel | Span kind |
| `status_code` | `span.status.status_code.name` | Standard OTel | Flattened status |
| `status_message` | `span.status.description` | Standard OTel | Flattened status description |
| `start_time` | `span.start_time` | Standard OTel | Start timestamp |
| `end_time` | `span.end_time` | Standard OTel | End timestamp |
| `attributes` | `span.attributes` | Standard OTel container | Contents may include standard, vendor, and custom keys |
| `events` | `span.events` | Standard OTel container | Event payloads may contain mixed attribute namespaces |
| `links` | `span.links` | Standard OTel container | Link attributes may contain mixed namespaces |
| `resource` | `span.resource` | Standard OTel associated metadata | Resource is standard OTel metadata |
| `scope` | `span.instrumentation_scope` | Standard OTel associated metadata | Instrumentation scope is standard OTel metadata |
| `span_time` | `start_time or now()` | Derived convenience field | Not an OTel field |
| `duration_ms` | `end_time - start_time` | Derived convenience field | Not an OTel field |
| `request_model` | `gen_ai.request.model` | Standard OTel GenAI semconv promoted to column | GenAI semconv is official but currently Development |
| `provider_name` | `gen_ai.provider.name` | Standard OTel GenAI semconv promoted to column | Official GenAI semantic convention |
| `server_address` | `server.address` | Standard OTel semconv promoted to column | Official stable semantic convention |
| `input_tokens` | `gen_ai.usage.input_tokens` | Standard OTel GenAI semconv promoted to column | Official GenAI semantic convention |
| `output_tokens` | `gen_ai.usage.output_tokens` | Standard OTel GenAI semconv promoted to column | Official GenAI semantic convention |
| `total_cost` | `operation.cost` | Custom / vendor-specific | Not found in official OTel semconv |
| `is_ai` | derived from `app.is_ai` or presence of `gen_ai.request.model` | Custom derived field | Not an OTel field |
| `is_embedding` | derived from `request_model` containing `embedding` | Custom derived field | Heuristic |
| `is_internal` | `app.is_internal` | Custom app attribute promoted to column | Not standard OTel |
| `conversation_id` | `app.conversation_id` | Custom app attribute promoted to column | Not standard OTel |
| `message_id` | `app.message_id` | Custom app attribute promoted to column | Not standard OTel |
| `total_time` | `app.total_time` | Custom app attribute promoted to column | Not standard OTel |

## Exact attribute keys explicitly read by `backend/app/otel.py`

The following keys are explicitly read or interpreted by the payload builder.

| Attribute key | Used for | Classification |
|---|---|---|
| `logfire.msg` | preferred formatted span name | Vendor-specific (Logfire) |
| `logfire.msg_template` | fallback formatted span name template | Vendor-specific (Logfire) |
| `app.is_ai` | derive `is_ai` | Custom app |
| `gen_ai.request.model` | `request_model`, derive `is_ai`, derive `is_embedding` | Standard OTel GenAI semconv |
| `gen_ai.provider.name` | `provider_name` | Standard OTel GenAI semconv |
| `server.address` | `server_address` | Standard OTel semconv |
| `gen_ai.usage.input_tokens` | `input_tokens` | Standard OTel GenAI semconv |
| `gen_ai.usage.output_tokens` | `output_tokens` | Standard OTel GenAI semconv |
| `operation.cost` | `total_cost` | Custom / vendor-specific |
| `app.is_internal` | `is_internal` | Custom app |
| `app.conversation_id` | `conversation_id` | Custom app |
| `app.message_id` | `message_id` | Custom app |
| `app.total_time` | `total_time` | Custom app |

## Notes on naming and standards

### Standard OTel fields
The following are part of the standard trace/span model or closely associated standard OTel metadata:

- `trace_id`
- `span_id`
- `parent_span_id`
- `name`
- `kind`
- `status_code`
- `status_message`
- `start_time`
- `end_time`
- `attributes`
- `events`
- `links`
- `resource`
- `scope`

### Standard semantic-convention fields promoted into columns
These are not top-level OTel span fields by themselves, but they are official semantic-convention attribute keys extracted into dedicated DB columns:

- `server.address`
- `gen_ai.request.model`
- `gen_ai.provider.name`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`

### GenAI semantic-convention stability
The GenAI semantic conventions are official OpenTelemetry semantic conventions, but they are currently marked **Development**, not Stable.

### Custom/vendor-specific keys
These are not official OpenTelemetry semantic conventions:

- `operation.cost`
- `app.*`
- `logfire.*`

`operation.cost` was not found in the official OpenTelemetry semantic-conventions documentation or repository and should be treated as custom/vendor-specific.

## Important caveat

Even though `attributes`, `events`, `links`, `resource`, and `scope` are standard OpenTelemetry containers, their contents can still include a mix of:

- standard OTel keys,
- standard OTel GenAI keys,
- vendor-specific keys,
- custom `app.*` keys.

So those columns are standard OTel **containers**, but their contents are not guaranteed to be purely standard.
