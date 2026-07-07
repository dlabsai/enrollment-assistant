import type { TraceDetail, TraceOverviewItem, TraceSpan } from "../types";
import { formatDurationMs } from "./trace-utils.ts";

export type ProjectedDataValueType = "json" | "markdown" | "scalar";

interface ReadableProjectedDataEntry {
    key: string;
    label: string;
    value: unknown;
    valueType?: ProjectedDataValueType;
    markdownValue?: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value);

const overviewItemStartMs = (item: TraceOverviewItem): number => {
    if (item.start_time === null) {
        return Number.POSITIVE_INFINITY;
    }
    const parsed = Date.parse(item.start_time);
    return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
};

export const sortProjectedOverviewItemsForDisplay = (
    items: TraceOverviewItem[],
): TraceOverviewItem[] => {
    const itemBySpanId = new Map(items.map((item) => [item.span_id, item]));
    const originalIndexBySpanId = new Map(
        items.map((item, index) => [item.span_id, index]),
    );
    const childrenByParentId = new Map<string, TraceOverviewItem[]>();
    const roots: TraceOverviewItem[] = [];

    for (const item of items) {
        const parentSpanId = item.parent_span_id;
        if (
            typeof parentSpanId === "string" &&
            parentSpanId.trim() !== "" &&
            itemBySpanId.has(parentSpanId)
        ) {
            const children = childrenByParentId.get(parentSpanId) ?? [];
            children.push(item);
            childrenByParentId.set(parentSpanId, children);
        } else {
            roots.push(item);
        }
    }

    const compareItems = (left: TraceOverviewItem, right: TraceOverviewItem): number => {
        const startDelta = overviewItemStartMs(left) - overviewItemStartMs(right);
        if (startDelta !== 0) {
            return startDelta;
        }
        return (
            (originalIndexBySpanId.get(left.span_id) ?? 0) -
            (originalIndexBySpanId.get(right.span_id) ?? 0)
        );
    };

    roots.sort(compareItems);
    for (const children of childrenByParentId.values()) {
        children.sort(compareItems);
    }

    const ordered: TraceOverviewItem[] = [];
    const visited = new Set<string>();
    const visit = (item: TraceOverviewItem): void => {
        if (visited.has(item.span_id)) {
            return;
        }
        visited.add(item.span_id);
        ordered.push(item);
        for (const child of childrenByParentId.get(item.span_id) ?? []) {
            visit(child);
        }
    };

    for (const root of roots) {
        visit(root);
    }

    if (ordered.length !== items.length) {
        for (const item of items.toSorted(compareItems)) {
            visit(item);
        }
    }

    return ordered;
};

const baseHiddenProjectedDataKeys = new Set([
    "cache_read_input_tokens",
    "cost_breakdown",
    "input_tokens",
    "input_messages",
    "input_text",
    "llm_response_metrics",
    "output_messages",
    "output_text",
    "output_tokens",
    "total_cost",
    "uncached_input_tokens",
]);

const projectedTimeSecondsKeys = new Set([
    "chatbot_times",
    "guardrail_time",
    "guardrail_times",
    "total_time",
]);

const projectedDataLabels: Record<string, string> = {
    agent_name: "Agent",
    arguments: "Arguments",
    blog_urls: "Blog URLs",
    cache_read_input_tokens: "Cache read tokens",
    call_id: "Call ID",
    chatbot_times: "Chatbot times",
    conversation_id: "Conversation ID",
    conversation_turn: "Turn",
    data_source_id: "Data source",
    documents: "Documents",
    embedding_duration_ms: "Embedding duration",
    embedding_input_tokens: "Embedding input tokens",
    embedding_model: "Embedding model",
    guardrail_failures: "Guardrail failures",
    guardrail_retries: "Chatbot retries",
    guardrail_time: "Guardrail time",
    guardrail_times: "Guardrail times",
    guardrails_blocked: "Guardrails blocked",
    guardrails_feedback: "Feedback",
    guardrails_is_valid: "Valid",
    input_tokens: "Input tokens",
    is_valid: "Valid",
    message_id: "Message ID",
    model: "Model",
    output_tokens: "Output tokens",
    case_name: "Case",
    dataset_name: "Dataset",
    evaluation_name: "Evaluation",
    evaluator_name: "Evaluator",
    explanation: "Explanation",
    max_concurrency: "Max concurrency",
    reasoning_effort: "Reasoning effort",
    repeats: "Repeats",
    result_kind: "Kind",
    run_index: "Run",
    score_label: "Score",
    score_value: "Score value",
    total_cases: "Total cases",
    total_runs: "Total runs",
    provider_name: "Provider",
    query: "Query",
    result: "Result",
    system_instructions: "System instructions",
    server_address: "Server",
    tool_name: "Tool",
    tool_type: "Tool type",
    top_k: "Top K",
    total_cost: "Cost",
    total_time: "Total time",
    unknown_urls: "Unknown URLs",
};

const formatProjectedDataLabel = (key: string): string =>
    projectedDataLabels[key] ??
    key
        .replaceAll("_", " ")
        .replaceAll(/\b\w/gu, (character) => character.toUpperCase());

const formatMillisecondsValue = (value: unknown): unknown => {
    if (typeof value === "number") {
        return formatDurationMs(value);
    }
    if (typeof value === "string") {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? formatDurationMs(parsed) : value;
    }
    return value;
};

const formatSecondsValue = (value: unknown): unknown => {
    if (typeof value === "number") {
        return formatDurationMs(value * 1000);
    }
    if (typeof value === "string") {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? formatDurationMs(parsed * 1000) : value;
    }
    if (Array.isArray(value)) {
        const formatted = value.map((entry) => formatSecondsValue(entry));
        return formatted.every((entry) => typeof entry === "string")
            ? formatted.join(", ")
            : value;
    }
    return value;
};

const formatProjectedDataValue = (key: string, value: unknown): unknown => {
    if (key === "embedding_duration_ms") {
        return formatMillisecondsValue(value);
    }
    if (projectedTimeSecondsKeys.has(key)) {
        return formatSecondsValue(value);
    }
    return value;
};

const markdownValueForProjectedDataEntry = (
    item: TraceOverviewItem,
    key: string,
    value: unknown,
): string | undefined => {
    if (item.type !== "tool" || key !== "result") {
        return undefined;
    }
    if (item.data.tool_name === "list_training_materials_tree" && typeof value === "string") {
        return value;
    }
    if (item.data.tool_name === "find_document_titles" && typeof value === "string") {
        return value;
    }
    return undefined;
};

const valueTypeForProjectedDataEntry = (
    markdownValue: string | undefined,
): ProjectedDataValueType | undefined =>
    markdownValue === undefined ? undefined : "markdown";

const orderProjectedDataEntries = (
    item: TraceOverviewItem,
    entries: ReadableProjectedDataEntry[],
): ReadableProjectedDataEntry[] => {
    if (
        item.type !== "agent" ||
        item.data.guardrails_is_valid === undefined ||
        !entries.some((entry) => entry.key === "system_instructions")
    ) {
        return entries;
    }

    const systemEntry = entries.find(
        (entry) => entry.key === "system_instructions",
    );
    if (systemEntry === undefined) {
        return entries;
    }

    const withoutSystem = entries.filter(
        (entry) => entry.key !== "system_instructions",
    );
    const feedbackIndex = withoutSystem.findIndex(
        (entry) => entry.key === "guardrails_feedback",
    );
    const validIndex = withoutSystem.findIndex(
        (entry) => entry.key === "guardrails_is_valid",
    );
    const insertAfterIndex = Math.max(feedbackIndex, validIndex);
    if (insertAfterIndex === -1) {
        return entries;
    }

    return [
        ...withoutSystem.slice(0, insertAfterIndex + 1),
        systemEntry,
        ...withoutSystem.slice(insertAfterIndex + 1),
    ];
};

const getHiddenProjectedDataKeys = (item: TraceOverviewItem): Set<string> => {
    const hidden = new Set(baseHiddenProjectedDataKeys);
    switch (item.type) {
        case "agent": {
            hidden.add("agent_name");
            hidden.add("model");
            hidden.add("reasoning_effort");
            break;
        }
        case "llm": {
            hidden.add("model");
            hidden.add("reasoning_effort");
            break;
        }
        case "tool": {
            hidden.add("tool_name");
            if (item.subtitle !== null && item.subtitle.trim() !== "") {
                hidden.add("tool_type");
            }
            break;
        }
        case "retrieval": {
            hidden.add("data_source_id");
            break;
        }
        case "conversation_turn": {
            hidden.add("total_time");
            break;
        }
        case "evaluation": {
            hidden.add("dataset_name");
            break;
        }
        case "evaluation_case": {
            hidden.add("case_name");
            hidden.add("run_index");
            break;
        }
        case "evaluation_result": {
            hidden.add("evaluation_name");
            break;
        }
        default: {
            break;
        }
    }
    return hidden;
};

export const getReadableProjectedDataEntries = (
    item: TraceOverviewItem,
): ReadableProjectedDataEntry[] => {
    const hidden = getHiddenProjectedDataKeys(item);
    const entries = Object.entries(item.data)
        .filter(
            ([key, value]) =>
                !hidden.has(key) && value !== undefined && value !== null,
        )
        .map(([key, value]) => {
            const formattedValue = formatProjectedDataValue(key, value);
            const markdownValue = markdownValueForProjectedDataEntry(
                item,
                key,
                formattedValue,
            );
            return {
                key,
                label: formatProjectedDataLabel(key),
                value: formattedValue,
                valueType: valueTypeForProjectedDataEntry(markdownValue),
                markdownValue,
            };
        });

    return orderProjectedDataEntries(item, entries);
};

export const hydrateSpansWithProjectedOutput = (
    detail: TraceDetail | undefined,
): TraceSpan[] => {
    if (detail === undefined) {
        return [];
    }

    const overviewBySpanId = new Map(
        detail.overview.map((item) => [item.span_id, item]),
    );

    return detail.spans.map((span) => {
        const attributes = span.attributes ?? {};
        if (attributes["gen_ai.output.messages"] !== undefined) {
            return span;
        }

        const projectedData = overviewBySpanId.get(span.span_id)?.data;
        if (projectedData === undefined) {
            return span;
        }

        const outputMessages = projectedData.output_messages;
        const outputText = projectedData.output_text;
        const nextOutputMessages = Array.isArray(outputMessages)
            ? outputMessages
            : typeof outputText === "string" && outputText.trim() !== ""
              ? [{ role: "assistant", content: outputText }]
              : undefined;

        if (nextOutputMessages === undefined) {
            return span;
        }

        return {
            ...span,
            attributes: {
                ...attributes,
                "gen_ai.output.messages": nextOutputMessages.filter((message) =>
                    isRecord(message),
                ),
            },
        };
    });
};
