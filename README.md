<h1 align="center">University Enrollment Assistant</h1>

Template for a self-hosted enrollment assistant with a public chat widget for prospective students, an internal app for admissions employees, answers grounded in the knowledge base, analytics, tracing, and eval tooling.

This template is based on real projects while avoiding unnecessary features. The codebase is meant to be adjusted for your institution and kept easy to navigate, refactor, and extend with coding agents.

Built by [DLabs.AI](https://dlabs.ai).

## Features

- Public website chat widget for prospective students.
- Contact and consent capture for public visitors.
- Public chat conversations that do not require user accounts.
- Public widget local chat history with a clear chat history control.
- Internal chat for admissions employees.
- Speech-to-text input and text-to-speech playback in the chat UI.
- Chat list with search, rename, delete, and title regeneration controls.
- Conversation, message, and feedback review with links back to the relevant chat and message.
- Review tables with text search, sorting, pagination, time ranges, owner filters, and detail sheets.
- Message diagnostics table with role, length, generation time, token counts, tool-call counts, guardrails-failure counts, blocked status, and trace links.
- Permission-controlled visibility for own chats, admissions employee chats, admin chats, dev chats, and public chats.
- Review sheets with summary toggle, transcript copy, previous and next navigation, and open in new tab actions.
- Multiple feedback entries per assistant message, so different reviewers can rate or comment on the same response.
- Feedback review table with rating filters, reviewer details, time filters, user filters, and Excel export.
- User-message editing, message branching, and active-response selection.
- Assistant-message activity, generation time, per-response cost, sources, tools, and guardrails diagnostics.
- Assistant-message sources icon showing the knowledge-base documents and assistant instructions used to generate the answer.
- Developer investigation chats linked to the source chat, source message, and feedback item, with diagnostic tools for transcript, metadata, sources, traces, branches, and knowledge-base content.
- Instructions editor for versioned chatbot, guardrails, grounding, investigation, summary, and title-generation instructions, with deploy and undeploy controls.
- Instructions test chat for trying assistant instruction changes before deployment.
- Guardrails feedback loop: check the draft answer, send feedback back to the chatbot when it fails, retry, then store and show the final approved or blocked response.
- Canned blocked response when guardrails reject all retries, while preserving the raw blocked response for diagnostics.
- Assistant-message guardrails icon and modal showing failed attempts, guardrails feedback, invalid URLs, and blocked status.
- Knowledge base with website, catalog, and internal training-material content.
- Public chat excludes internal training materials.
- Knowledge-base viewer with phrase search, full-text search, similarity search, chunks, and tree views.
- Knowledge-base build controls for incremental builds, force rebuilds, live progress, logs, resume, and copying the runtime knowledge base into the eval database.
- Knowledge-base build jobs with status and trigger filters, source statistics, and new, changed, and deleted document details.
- Knowledge-base controls for content visibility, folder views, and exclusion audit events.
- Chat analytics with platform filters, time ranges, conversation volume, message volume, chat length, response time, and messages-by-hour charts.
- Public widget analytics with lead totals and leads over time charts.
- Usage dashboard for model calls, embeddings, tokens, latency, cost, model breakdowns, platform filters, model filters, and recent traces.
- OpenTelemetry trace storage using GenAI semantic conventions, with optional OTLP export to compatible observability backends.
- Trace browser for chat turns, chatbot, guardrails, grounding, eval judges, model calls, tool calls, knowledge-base lookups, URL guardrails, eval case runs and results, knowledge-base builds, embedding batches, assistant instructions, inputs, outputs, tokens, and cost, with raw span details, compact debug summaries, durations, relative offsets, and span timeline visualization.
- Eval runner for chatbot and guardrails suites with case selection, repeats, concurrency, pass thresholds, model overrides, live progress, live logs, and cancellation support.
- Eval case management for built-in and custom cases with create, edit, hide, restore, and public/internal chat controls.
- Eval reports with pass rates, case and run details, assertion, score, and label results, outputs, durations, model configurations, compare views, trend views, and model-analysis views.
- Eval trace browser linked from report runs.
- Separate database for eval and test artifacts.
- User, admin, and dev groups with fine-grained page and action permissions and per-user overrides.
- Optional Teams SSO.
- Application settings overrides for institution details and the canned guardrails blocked response.
- Configurable model list and per-agent defaults.
- Internal chat model selector with saved model favorites and presets.
- Demo University sample knowledge-base content for local development.

## Permissions

The internal app uses user, admin, and dev groups, plus per-user overrides, to control:

- Page access for Chats, Investigations, Messages, Instructions editor, Traces, KB Builder, KB Viewer, KB Controls, Access Controls, Usage, Chat Analytics, Public Analytics, Evals, and Settings.
- Chat actions and diagnostics, including regenerate, activity timeline, trace links, model selection, generation timing tooltip, assistant-message sources, tool details, per-response cost, and guardrails-failure details.
- Review scope for conversations owned by the current user, admissions employees, admins, and devs.
- Chats review diagnostics, including trace links and the cost column.
- Developer investigation chats, including creating investigations, sending investigation messages, and reviewing investigation details.

## Screenshots

| Public widget |
|:---:|
| ![Public widget in embedded panel with consent-first flow before messaging](assets/public.png) |

| Public analytics |
|:---:|
| ![Public analytics dashboard showing leads over time for the widget](assets/public_analytics.png) |

| Chats review |
|:---:|
| ![Chats operations view with platform filters, search, and conversation detail sheet](assets/chats.png) |

| Internal chat |
|:---:|
| ![Internal chat page with message controls and activity timeline](assets/chat.png) |

| Instructions editor |
|:---:|
| ![Instructions editor with template sections, version controls, deploy flow, and test chat panel](assets/instructions.png) |

| Chat analytics |
|:---:|
| ![Chat analytics page with conversation and response-performance charts](assets/chat_analytics.png) |

| Usage |
|:---:|
| ![Usage dashboard with token totals, cost, latency, model breakdown, and recent requests](assets/usage.png) |

| Traces |
|:---:|
| ![Trace list with filters and span counts](assets/traces.png) |

| Trace detail |
|:---:|
| ![Trace detail view showing structured and raw span inspection](assets/trace.png) |

| Evals |
|:---:|
| ![Evals report view with generated report output and failed-case breakdown](assets/eval_1.png) |

| Evals configuration |
|:---:|
| ![Run evals card with suite selection, test-case picker, and live run logs](assets/evals_2.png) |

| Evals comparison |
|:---:|
| ![Evals analysis views for baseline-vs-compare deltas and trends](assets/evals_3.png) |

| Settings |
|:---:|
| ![Settings view for application configuration](assets/settings.png) |

## Setup

See [`docs/setup.md`](docs/setup.md).

## License

[MIT](LICENSE)
