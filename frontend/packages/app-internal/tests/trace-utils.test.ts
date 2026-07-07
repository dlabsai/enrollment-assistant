import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    getReadableProjectedDataEntries,
    hydrateSpansWithProjectedOutput,
    sortProjectedOverviewItemsForDisplay,
} from "../src/traces/lib/trace-projection-utils.ts";
import {
    extractRequestTools,
    extractResponseMessages,
    extractResponseToolCalls,
    extractToolResults,
    formatDurationMs,
} from "../src/traces/lib/trace-utils.ts";
import type {
    TraceDetail,
    TraceOverviewItem,
    TraceSpan,
} from "../src/traces/types/index.ts";

const baseOverviewItem = (
    overrides: Partial<TraceOverviewItem>,
): TraceOverviewItem => ({
    id: "span-1",
    span_id: "span-1",
    parent_span_id: null,
    type: "other",
    title: "Span",
    subtitle: null,
    start_time: "2026-04-27T12:00:00Z",
    duration_ms: 1000,
    status_code: "OK",
    data: {},
    ...overrides,
});

const baseSpan = (overrides: Partial<TraceSpan>): TraceSpan => ({
    span_id: "span-1",
    parent_span_id: null,
    name: "chat azure/gpt-5.5",
    kind: "INTERNAL",
    status_code: "OK",
    status_message: null,
    start_time: "2026-04-27T12:00:00Z",
    end_time: "2026-04-27T12:00:01Z",
    duration_ms: 1000,
    attributes: {},
    events: null,
    links: null,
    resource: null,
    scope: null,
    ...overrides,
});

describe("trace tool parsing", () => {
    it("reads OTel GenAI tool arguments and full result payloads", () => {
        const result = [
            {
                type: "WEBSITE_PAGE",
                id: 12,
                title: "Financial Aid",
                sequence_number: 1,
                content: "full chunk content".repeat(100),
            },
        ];
        const attributes = {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "find_document_chunks",
            "gen_ai.tool.type": "datastore",
            "gen_ai.tool.call.arguments": JSON.stringify({
                content_search_query: "financial aid",
            }),
            "gen_ai.tool.call.result": JSON.stringify(result),
        };

        const [requestTool] = extractRequestTools(attributes);
        const [toolResult] = extractToolResults(attributes);

        assert.equal(requestTool?.name, "find_document_chunks");
        assert.deepEqual(JSON.parse(requestTool?.arguments ?? "{}"), {
            content_search_query: "financial aid",
        });
        assert.equal(toolResult?.name, "find_document_chunks");
        assert.deepEqual(JSON.parse(toolResult?.result ?? "[]"), result);
    });

    it("preserves compact find_document_chunks tool result arrays", () => {
        const result = [
            {
                content: "same chunk",
                sources: { website_page: [[101, [3, 5], "Admissions"]] },
            },
        ];
        const attributes = {
            "gen_ai.tool.name": "find_document_chunks",
            "gen_ai.tool.call.result": JSON.stringify(result),
        };

        const [toolResult] = extractToolResults(attributes);

        assert.equal(toolResult?.name, "find_document_chunks");
        assert.deepEqual(JSON.parse(toolResult?.result ?? "{}"), result);
    });

    it("deduplicates final_result tool calls when a message has parts and tool_calls", () => {
        const finalResultToolCall = {
            id: "final-result-1",
            type: "function",
            function: {
                name: "final_result",
                arguments: JSON.stringify({ is_valid: true, feedback: null }),
            },
        };
        const attributes = {
            response_data: JSON.stringify({
                messages: [
                    {
                        role: "assistant",
                        content: null,
                        parts: [
                            {
                                type: "tool_call",
                                id: finalResultToolCall.id,
                                function: finalResultToolCall.function,
                            },
                        ],
                        tool_calls: [finalResultToolCall],
                    },
                ],
            }),
        };

        const [message] = extractResponseMessages(attributes);

        assert.equal(message?.parts?.length, 1);
        assert.equal(message?.parts?.[0]?.type, "tool_call");
        assert.deepEqual(JSON.parse(message.parts[0]?.content ?? "{}"), {
            is_valid: true,
            feedback: null,
        });
    });

    it("reads assistant text from OTel GenAI output messages", () => {
        const attributes = {
            "gen_ai.output.messages": JSON.stringify([
                {
                    role: "assistant",
                    content: "Tell them Demo University is accredited.",
                },
            ]),
        };

        const [message] = extractResponseMessages(attributes);

        assert.equal(message?.role, "assistant");
        assert.equal(
            message?.content,
            "Tell them Demo University is accredited.",
        );
    });

    it("reads tool calls from OpenAI choices responses", () => {
        const attributes = {
            response_data: JSON.stringify({
                choices: [
                    {
                        message: {
                            role: "assistant",
                            content: null,
                            tool_calls: [
                                {
                                    id: "call-1",
                                    type: "function",
                                    function: {
                                        name: "find_document_chunks",
                                        arguments: JSON.stringify({ query: "tuition" }),
                                    },
                                },
                            ],
                        },
                    },
                ],
            }),
        };

        const [toolCall] = extractResponseToolCalls(attributes);
        const [message] = extractResponseMessages(attributes);

        assert.equal(toolCall?.name, "find_document_chunks");
        assert.deepEqual(JSON.parse(toolCall?.arguments ?? "{}"), {
            query: "tuition",
        });
        assert.equal(message?.role, "assistant");
        assert.equal(message?.parts?.[0]?.type, "tool_call");
    });
});

describe("structured trace response rendering data", () => {
    it("renders positive sub-millisecond durations as less than one millisecond", () => {
        assert.equal(formatDurationMs(0.4), "<1ms");
        assert.equal(formatDurationMs(0), "-");
    });

    it("hides standard model fields from readable projected details", () => {
        const entries = getReadableProjectedDataEntries({
            id: "llm-span",
            span_id: "llm-span",
            parent_span_id: null,
            type: "llm",
            title: "LLM: azure/gpt-5.5",
            subtitle: null,
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 1000,
            status_code: "OK",
            data: {
                model: "azure/gpt-5.5",
                provider_name: "azure.ai.openai",
            },
        });

        assert.deepEqual(
            entries.map((entry) => [entry.key, entry.label, entry.value]),
            [["provider_name", "Provider", "azure.ai.openai"]],
        );
    });

    it("hides duplicate response and verbose metrics from readable projected details", () => {
        const entries = getReadableProjectedDataEntries({
            id: "chatbot-span",
            span_id: "chatbot-span",
            parent_span_id: null,
            type: "agent",
            title: "Agent: chatbot",
            subtitle: "azure/gpt-5.5",
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 1000,
            status_code: "UNSET",
            data: {
                agent_name: "chatbot",
                model: "azure/gpt-5.5",
                input_tokens: 4813,
                output_tokens: 65,
                llm_response_metrics: [{ request_index: 1, output_tokens: 65 }],
                output_messages: [
                    {
                        role: "assistant",
                        content: "Tell them Demo University is accredited.",
                    },
                ],
                output_text: "Tell them Demo University is accredited.",
            },
        });

        assert.deepEqual(
            entries.map((entry) => [entry.key, entry.label, entry.value]),
            [],
        );
    });

    it("formats embedded tool embedding duration like other durations", () => {
        const entries = getReadableProjectedDataEntries({
            id: "tool-span",
            span_id: "tool-span",
            parent_span_id: null,
            type: "tool",
            title: "Tool: find_document_chunks",
            subtitle: "datastore",
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 1200,
            status_code: "OK",
            data: {
                tool_name: "find_document_chunks",
                tool_type: "datastore",
                embedding_model: "text-embedding-3-large",
                embedding_duration_ms: 938,
                embedding_input_tokens: 6,
            },
        });

        assert.deepEqual(
            entries.map((entry) => [entry.key, entry.label, entry.value]),
            [
                ["embedding_model", "Embedding model", "text-embedding-3-large"],
                ["embedding_duration_ms", "Embedding duration", "938ms"],
                ["embedding_input_tokens", "Embedding input tokens", 6],
            ],
        );
    });

    it("formats projected conversation timings", () => {
        const conversationEntries = getReadableProjectedDataEntries({
            id: "conversation-turn-span",
            span_id: "conversation-turn-span",
            parent_span_id: null,
            type: "conversation_turn",
            title: "Conversation Turn",
            subtitle: null,
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 12500,
            status_code: "OK",
            data: {
                total_time: 12.5,
                guardrail_time: 1.25,
                chatbot_times: [3.1, 4.2],
            },
        });

        assert.deepEqual(
            conversationEntries.map((entry) => [entry.key, entry.label, entry.value]),
            [
                ["guardrail_time", "Guardrail time", "1.25s"],
                ["chatbot_times", "Chatbot times", "3.10s, 4.20s"],
            ],
        );
    });

    it("keeps guardrails validity and feedback in readable projected details", () => {
        const invalidEntries = getReadableProjectedDataEntries({
            id: "guardrails-span",
            span_id: "guardrails-span",
            parent_span_id: null,
            type: "agent",
            title: "Agent: guardrails",
            subtitle: "azure/gpt-5.5",
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 1000,
            status_code: "UNSET",
            data: {
                agent_name: "guardrails",
                guardrails_is_valid: false,
                guardrails_feedback: "Use allowed URLs only.",
            },
        });

        assert.deepEqual(
            invalidEntries.map((entry) => [entry.key, entry.label, entry.value]),
            [
                ["guardrails_is_valid", "Valid", false],
                ["guardrails_feedback", "Feedback", "Use allowed URLs only."],
            ],
        );

        const validEntries = getReadableProjectedDataEntries({
            id: "guardrails-span",
            span_id: "guardrails-span",
            parent_span_id: null,
            type: "agent",
            title: "Agent: guardrails",
            subtitle: "azure/gpt-5.5",
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 1000,
            status_code: "UNSET",
            data: {
                agent_name: "guardrails",
                guardrails_is_valid: true,
            },
        });

        assert.deepEqual(
            validEntries.map((entry) => [entry.key, entry.label, entry.value]),
            [["guardrails_is_valid", "Valid", true]],
        );
    });

    it("sorts projected overview rows by hierarchy before sibling time", () => {
        const rows = sortProjectedOverviewItemsForDisplay([
            baseOverviewItem({
                id: "root",
                span_id: "root",
                type: "evaluation",
                title: "Evaluation: demo_va_chatbot_eval",
                start_time: "2026-04-27T12:00:00.000Z",
            }),
            baseOverviewItem({
                id: "case-a",
                span_id: "case-a",
                parent_span_id: "root",
                type: "evaluation_case",
                title: "Case Run: internal_greeting_response #1",
                start_time: "2026-04-27T12:00:00.001Z",
            }),
            baseOverviewItem({
                id: "case-b",
                span_id: "case-b",
                parent_span_id: "root",
                type: "evaluation_case",
                title: "Case Run: internal_program_inquiry_general #1",
                start_time: "2026-04-27T12:00:00.002Z",
            }),
            baseOverviewItem({
                id: "case-b-turn",
                span_id: "case-b-turn",
                parent_span_id: "case-b",
                type: "conversation_turn",
                title: "Conversation Turn",
                start_time: "2026-04-27T12:00:00.003Z",
            }),
            baseOverviewItem({
                id: "case-a-turn",
                span_id: "case-a-turn",
                parent_span_id: "case-a",
                type: "conversation_turn",
                title: "Conversation Turn",
                start_time: "2026-04-27T12:00:00.004Z",
            }),
        ]);

        assert.deepEqual(
            rows.map((row) => row.span_id),
            ["root", "case-a", "case-a-turn", "case-b", "case-b-turn"],
        );
    });

    it("formats eval projection details without duplicate title fields", () => {
        const resultEntries = getReadableProjectedDataEntries({
            id: "eval-result-span",
            span_id: "eval-result-span",
            parent_span_id: "case-run-span",
            type: "evaluation_result",
            title: "Evaluation Result: passed",
            subtitle: "fail",
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 10,
            status_code: "OK",
            data: {
                evaluation_name: "passed",
                score_label: "fail",
                score_value: 0,
                explanation: "Response was not grounded.",
                evaluator_name: "ChatbotJudge",
                result_kind: "assertion",
                case_name: "internal_greeting_response",
                run_index: 1,
            },
        });

        assert.deepEqual(
            resultEntries.map((entry) => [entry.key, entry.label, entry.value]),
            [
                ["score_label", "Score", "fail"],
                ["score_value", "Score value", 0],
                ["explanation", "Explanation", "Response was not grounded."],
                ["evaluator_name", "Evaluator", "ChatbotJudge"],
                ["result_kind", "Kind", "assertion"],
                ["case_name", "Case", "internal_greeting_response"],
                ["run_index", "Run", 1],
            ],
        );

        const caseEntries = getReadableProjectedDataEntries({
            id: "case-run-span",
            span_id: "case-run-span",
            parent_span_id: "eval-root-span",
            type: "evaluation_case",
            title: "Case Run: internal_greeting_response #1",
            subtitle: null,
            start_time: "2026-04-27T12:00:00Z",
            duration_ms: 1000,
            status_code: "OK",
            data: {
                case_name: "internal_greeting_response",
                run_index: 1,
            },
        });

        assert.deepEqual(caseEntries, []);
    });

    it("hydrates projected output messages before building structured span details", () => {
        const detail: TraceDetail = {
            trace_id: "trace-1",
            started_at: "2026-04-27T12:00:00Z",
            duration_ms: 1000,
            span_count: 1,
            is_public: false,
            conversation_id: "conversation-1",
            spans: [
                baseSpan({
                    span_id: "chatbot-span",
                    attributes: {
                        "gen_ai.agent.name": "chatbot",
                        "gen_ai.usage.output_tokens": 12,
                    },
                }),
            ],
            overview: [
                {
                    id: "chatbot-span",
                    span_id: "chatbot-span",
                    parent_span_id: null,
                    type: "agent",
                    title: "Agent: chatbot",
                    subtitle: "azure/gpt-5.5",
                    start_time: "2026-04-27T12:00:00Z",
                    duration_ms: 1000,
                    status_code: "OK",
                    data: {
                        output_text: "Tell them Demo University is accredited.",
                    },
                },
            ],
        };

        const [hydratedSpan] = hydrateSpansWithProjectedOutput(detail);
        assert.ok(hydratedSpan);

        assert.deepEqual(extractResponseMessages(hydratedSpan.attributes ?? {}), [
            {
                role: "assistant",
                content: "Tell them Demo University is accredited.",
                parts: undefined,
            },
        ]);
    });
});
