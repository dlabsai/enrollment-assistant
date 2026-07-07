import { formatEstimatedUsdCost } from "../../lib/number-format";
import {
    extractRequestMessages,
    extractRequestTools,
    extractResponseMessages,
    extractResponseToolCalls,
    extractToolResults,
    getResolvedSpanTiming,
    getStringAttribute,
    type TraceMessage,
} from "../lib/trace-utils";
import {
    formatSpanDuration,
    getSpanTimelineLayout,
} from "../lib/trace-view-utils";
import type { TraceSpan } from "../types";
import {
    formatNumeric,
    formatOffset,
    formatTimestampWithSeconds,
    getNumericAttribute,
} from "./trace-turn-metrics-utils";

interface ToolCall {
    name: string;
    arguments: string;
}
interface ToolResult {
    name: string;
    result: string;
}

interface SpanDetailModel {
    id: string;
    title: string;
    subtitle?: string;
    durationLabel: string;
    isError: boolean;
    offsetPct: number;
    widthPct: number;
    timing: { start: string; end: string; offset: string };
    metadataEntries: { label: string; value: string }[];
    usageEntries: { label: string; value: string }[];
    appEntries: { key: string; value: unknown }[];
    systemInstructions?: string;
    prompt?: string;
    requestMessages: TraceMessage[];
    requestTools: ToolCall[];
    responseMessages: TraceMessage[];
    responseText?: string;
    toolCalls: ToolCall[];
    toolResults: ToolResult[];
}

export const buildSpanDetailModel = ({
    span,
    traceStart,
    traceEnd,
    title,
    subtitle,
}: {
    span: TraceSpan;
    traceStart: number | undefined;
    traceEnd: number | undefined;
    title: string;
    subtitle: string | undefined;
}): SpanDetailModel => {
    const attributes = span.attributes ?? {};
    const requestMessages = extractRequestMessages(attributes);
    const responseMessages = extractResponseMessages(attributes);
    const prompt = getStringAttribute(attributes, "gen_ai.request.prompt");
    const responseText =
        getStringAttribute(attributes, "gen_ai.response.text") ??
        getStringAttribute(attributes, "gen_ai.response.message");
    const toolCalls = extractResponseToolCalls(attributes);
    const toolResults = extractToolResults(attributes);
    const requestTools = extractRequestTools(attributes);
    const provider = getStringAttribute(attributes, "gen_ai.provider.name");
    const model = getStringAttribute(attributes, "gen_ai.request.model");
    const operationName = getStringAttribute(
        attributes,
        "gen_ai.operation.name",
    );
    const systemInstructions = getStringAttribute(
        attributes,
        "gen_ai.system_instructions",
    );
    const inputTokens = getNumericAttribute(
        attributes,
        "gen_ai.usage.input_tokens",
    );
    const outputTokens = getNumericAttribute(
        attributes,
        "gen_ai.usage.output_tokens",
    );
    const cacheTokens = getNumericAttribute(
        attributes,
        "gen_ai.usage.cache_read.input_tokens",
    );
    const cost = getNumericAttribute(attributes, "operation.cost");

    const appEntries = Object.entries(attributes)
        .filter(([key, value]) => key.startsWith("app.") && value !== undefined)
        .map(([key, value]) => ({
            key,
            value,
        }));

    const timing = getResolvedSpanTiming(span);
    const timelineLayout = getSpanTimelineLayout(span, traceStart, traceEnd);
    const offset = timelineLayout?.offsetMs;
    const offsetPct = timelineLayout?.offsetPct ?? 0;
    const widthPct = timelineLayout?.widthPct ?? 2;

    const metadataEntries = [
        { label: "Model", value: model },
        { label: "Provider", value: provider },
        { label: "Operation", value: operationName },
    ].filter((entry): entry is { label: string; value: string } =>
        Boolean(entry.value),
    );

    const usageEntries = [
        { label: "Input tokens", value: formatNumeric(inputTokens) },
        { label: "Output tokens", value: formatNumeric(outputTokens) },
        { label: "Cache read tokens", value: formatNumeric(cacheTokens) },
        { label: "Cost", value: formatEstimatedUsdCost(cost) },
    ].filter((entry) => entry.value !== "-");

    return {
        id: span.span_id,
        title,
        subtitle: subtitle ?? undefined,
        durationLabel: formatSpanDuration(span),
        isError: span.status_code === "ERROR",
        offsetPct,
        widthPct,
        timing: {
            start: formatTimestampWithSeconds(timing.start),
            end: formatTimestampWithSeconds(timing.end),
            offset: formatOffset(offset),
        },
        metadataEntries,
        usageEntries,
        appEntries,
        systemInstructions: systemInstructions ?? undefined,
        prompt: prompt ?? undefined,
        requestMessages,
        requestTools,
        responseMessages,
        responseText: responseText ?? undefined,
        toolCalls,
        toolResults,
    };
};
