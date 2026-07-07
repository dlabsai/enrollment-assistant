import { formatTableTimestamp } from "../../lib/date-format.ts";
import { formatLocaleNumber } from "../../lib/number-format.ts";
import type { TraceSpan } from "../types";

interface SpanNode {
    span: TraceSpan;
    depth: number;
}

export interface TraceMessagePart {
    type: string;
    content?: string;
    raw: unknown;
}

export interface TraceMessage {
    role: string;
    content: string;
    parts?: TraceMessagePart[];
}

interface ResolvedSpanTiming {
    start: number | undefined;
    end: number | undefined;
    durationMs: number | undefined;
}

const normalizeString = (
    value: string | null | undefined,
): string | undefined => value ?? undefined;

export const formatTimestamp = (value: string | null | undefined): string =>
    formatTableTimestamp(normalizeString(value));

export const formatDurationMs = (
    durationMs: number | null | undefined,
): string => {
    const normalized = durationMs ?? undefined;
    if (normalized === undefined || normalized <= 0) {
        return "-";
    }
    if (normalized < 1) {
        return "<1ms";
    }
    if (normalized < 1000) {
        return `${formatLocaleNumber(Math.round(normalized))}ms`;
    }
    return `${formatLocaleNumber(normalized / 1000, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}s`;
};

export const formatPlatform = (value: boolean | null | undefined): string => {
    if (value === true) {
        return "Public";
    }
    if (value === false) {
        return "Internal";
    }
    return "Unknown";
};

export const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" &&
    value instanceof Object &&
    !Array.isArray(value);

const parseJsonString = (value: string): unknown => {
    const trimmed = value.trim();
    if (
        trimmed === "" ||
        (!trimmed.startsWith("{") && !trimmed.startsWith("["))
    ) {
        return undefined;
    }
    try {
        return JSON.parse(trimmed);
    } catch {
        return undefined;
    }
};

export const parseJsonRecursively = (value: unknown): unknown => {
    if (typeof value === "string") {
        const parsed = parseJsonString(value);
        if (parsed !== undefined) {
            return parseJsonRecursively(parsed);
        }
        return value;
    }
    if (Array.isArray(value)) {
        return value.map((entry) => parseJsonRecursively(entry));
    }
    if (isRecord(value)) {
        return Object.fromEntries(
            Object.entries(value).map(([key, entry]) => [
                key,
                parseJsonRecursively(entry),
            ]),
        );
    }
    return value;
};

const toTimestamp = (value: string | null | undefined): number | undefined => {
    const normalized = normalizeString(value);
    if (normalized === undefined || normalized.trim() === "") {
        return undefined;
    }
    const parsed = Date.parse(normalized);
    return Number.isNaN(parsed) ? undefined : parsed;
};

export const getSpanStart = (span: TraceSpan): number | undefined =>
    toTimestamp(span.start_time);

export const getSpanEnd = (span: TraceSpan): number | undefined =>
    toTimestamp(span.end_time ?? span.start_time ?? undefined);

const getRawSpanEnd = (span: TraceSpan): number | undefined =>
    toTimestamp(span.end_time);

const parseDurationFromSpanName = (name: string): number | undefined => {
    const match = /\btook\s+(?<value>[\d.]+)\s*(?<unit>ms|s)\b/iu.exec(name);
    if (match === null) {
        return undefined;
    }

    const rawValue = match.groups?.value;
    const unit = match.groups?.unit?.toLowerCase();
    const value = rawValue === undefined ? Number.NaN : Number(rawValue);
    if (!Number.isFinite(value) || value < 0) {
        return undefined;
    }

    return unit === "s" ? value * 1000 : value;
};

const getPositiveDurationMs = (span: TraceSpan): number | undefined => {
    const durationMs = span.duration_ms;
    return typeof durationMs === "number" &&
        Number.isFinite(durationMs) &&
        durationMs > 0
        ? durationMs
        : undefined;
};

const getNegativeDurationMs = (span: TraceSpan): number | undefined => {
    const durationMs = span.duration_ms;
    return typeof durationMs === "number" &&
        Number.isFinite(durationMs) &&
        durationMs < 0
        ? Math.abs(durationMs)
        : undefined;
};

export const getResolvedSpanTiming = (span: TraceSpan): ResolvedSpanTiming => {
    const start = getSpanStart(span);
    const end = getRawSpanEnd(span) ?? start;
    const positiveDurationMs = getPositiveDurationMs(span);
    const negativeDurationMs = getNegativeDurationMs(span);
    const parsedDurationMs = parseDurationFromSpanName(span.name);
    const spanType =
        typeof span.attributes?.["logfire.span_type"] === "string"
            ? span.attributes["logfire.span_type"]
            : undefined;

    if (start !== undefined && end !== undefined && end > start) {
        return {
            start,
            end,
            durationMs: end - start,
        };
    }

    if (
        spanType === "log" &&
        end !== undefined &&
        parsedDurationMs !== undefined
    ) {
        return {
            start: end - parsedDurationMs,
            end,
            durationMs: parsedDurationMs,
        };
    }

    if (start !== undefined && negativeDurationMs !== undefined) {
        return {
            start,
            end: start + negativeDurationMs,
            durationMs: negativeDurationMs,
        };
    }

    if (start !== undefined && positiveDurationMs !== undefined) {
        return {
            start,
            end: start + positiveDurationMs,
            durationMs: positiveDurationMs,
        };
    }

    if (start !== undefined && end !== undefined && end < start) {
        const recoveredDurationMs = Math.abs(end - start);
        return {
            start,
            end: start + recoveredDurationMs,
            durationMs: recoveredDurationMs,
        };
    }

    if (
        spanType === "log" &&
        end !== undefined &&
        parsedDurationMs !== undefined
    ) {
        return {
            start: end - parsedDurationMs,
            end,
            durationMs: parsedDurationMs,
        };
    }

    if (start !== undefined && parsedDurationMs !== undefined) {
        return {
            start,
            end: start + parsedDurationMs,
            durationMs: parsedDurationMs,
        };
    }

    return {
        start,
        end,
        durationMs: undefined,
    };
};

export const getResolvedTraceTiming = (
    spans: TraceSpan[],
): ResolvedSpanTiming => {
    const startTimes: number[] = [];
    const endTimes: number[] = [];

    for (const span of spans) {
        const timing = getResolvedSpanTiming(span);
        if (timing.start !== undefined) {
            startTimes.push(timing.start);
        }
        if (timing.end !== undefined) {
            endTimes.push(timing.end);
        }
    }

    const start = startTimes.length > 0 ? Math.min(...startTimes) : undefined;
    const end = endTimes.length > 0 ? Math.max(...endTimes) : undefined;

    return {
        start,
        end,
        durationMs:
            start !== undefined && end !== undefined && end > start
                ? end - start
                : undefined,
    };
};

export const buildSpanTree = (spans: TraceSpan[]): SpanNode[] => {
    const rootKey = "__root__";
    const children = new Map<string, TraceSpan[]>();
    const spanIds = new Set(spans.map((span) => span.span_id));

    for (const span of spans) {
        const parentId = span.parent_span_id;
        const parent =
            typeof parentId === "string" &&
            parentId !== "" &&
            spanIds.has(parentId)
                ? parentId
                : rootKey;
        const list = children.get(parent) ?? [];
        list.push(span);
        children.set(parent, list);
    }

    for (const [key, list] of children.entries()) {
        const sorted = list.toSorted((left, right) => {
            const leftStart = getResolvedSpanTiming(left).start ?? 0;
            const rightStart = getResolvedSpanTiming(right).start ?? 0;
            return leftStart - rightStart;
        });
        children.set(key, sorted);
    }

    const ordered: SpanNode[] = [];
    const roots = children.get(rootKey) ?? [];

    const walk = (span: TraceSpan, depth: number): void => {
        ordered.push({ span, depth });
        const nested = children.get(span.span_id) ?? [];
        for (const child of nested) {
            walk(child, depth + 1);
        }
    };

    for (const root of roots) {
        walk(root, 0);
    }

    return ordered;
};

const stringifyValue = (value: unknown): string => {
    if (typeof value === "string") {
        return value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }
    return JSON.stringify(value, undefined, 2);
};

const resolveMessageContent = (value: unknown): string => {
    if (typeof value === "string") {
        return value;
    }
    if (Array.isArray(value)) {
        const hasStructured = value.some(
            (entry) => isRecord(entry) || Array.isArray(entry),
        );
        if (hasStructured) {
            return JSON.stringify(value, undefined, 2);
        }
        return value.map((part) => stringifyValue(part)).join("\n");
    }
    if (value === undefined) {
        return "";
    }
    return stringifyValue(value);
};

const parseJsonValue: (value: unknown) => unknown = (value) => {
    if (typeof value !== "string") {
        return value;
    }
    try {
        return JSON.parse(value) as unknown;
    } catch {
        return value;
    }
};

const normalizeMessageParts = (value: unknown): TraceMessagePart[] => {
    const parsed = parseJsonValue(value);
    const parts = Array.isArray(parsed) ? (parsed as unknown[]) : [];

    return parts.map((part) => {
        if (!isRecord(part)) {
            return {
                type: "unknown",
                content: resolveMessageContent(part),
                raw: part,
            };
        }
        const type = typeof part.type === "string" ? part.type : "unknown";
        const functionData = isRecord(part.function) ? part.function : undefined;
        const contentValue =
            part.content ??
            part.text ??
            part.output ??
            part.arguments ??
            functionData?.arguments ??
            part.result;
        const content =
            contentValue === undefined
                ? undefined
                : resolveMessageContent(contentValue);
        return {
            type,
            content,
            raw: part,
        };
    });
};

export const getStringAttribute = (
    attributes: Record<string, unknown>,
    key: string,
): string | undefined => {
    const value = attributes[key];
    return typeof value === "string" ? value : undefined;
};

const resolveFirstString = (...values: unknown[]): string | undefined =>
    values.find((value): value is string => typeof value === "string");

interface DetailedToolCall {
    id?: string;
    name: string;
    arguments: string;
}

interface DetailedToolResult {
    id?: string;
    name?: string;
    result: string;
}

const normalizeDetailedToolCallEntry = (
    entry: unknown,
): DetailedToolCall | undefined => {
    if (!isRecord(entry)) {
        return undefined;
    }
    const {
        id: entryId,
        name: entryName,
        tool: entryTool,
        tool_name: entryToolName,
        arguments: entryArguments,
        function: entryFunction,
        args,
        input,
    } = entry;
    const functionData = isRecord(entryFunction) ? entryFunction : undefined;
    const { name: functionName, arguments: functionArguments } =
        functionData ?? {};
    const name =
        resolveFirstString(entryName, entryToolName, entryTool, functionName) ??
        "tool";
    const argumentsValue =
        entryArguments ?? functionArguments ?? args ?? input ?? {};
    const normalizedArguments = stringifyValue(parseJsonValue(argumentsValue));
    return {
        id: typeof entryId === "string" ? entryId : undefined,
        name,
        arguments: normalizedArguments,
    };
};

const normalizeToolCallEntry = (
    entry: unknown,
): { name: string; arguments: string } | undefined => {
    const normalized = normalizeDetailedToolCallEntry(entry);
    if (normalized === undefined) {
        return undefined;
    }
    return {
        name: normalized.name,
        arguments: normalized.arguments,
    };
};

const normalizeToolResultEntry = (
    entry: unknown,
): { name: string; result: string } | undefined => {
    if (!isRecord(entry)) {
        return undefined;
    }
    const {
        name: entryName,
        tool: entryTool,
        tool_name: entryToolName,
        result,
        output,
        response,
        content,
        value,
        data,
    } = entry;

    const name =
        resolveFirstString(entryName, entryToolName, entryTool) ?? "tool";
    const resultValue =
        result ?? output ?? response ?? content ?? value ?? data;
    if (resultValue === undefined) {
        return undefined;
    }
    return {
        name,
        result: stringifyValue(parseJsonValue(resultValue)),
    };
};

const extractToolCallAttributes = (
    attributes: Record<string, unknown>,
): { name: string; arguments: string }[] => {
    const calls: { name: string; arguments: string }[] = [];
    const {
        "gen_ai.tool.call.arguments": callArguments,
        "gen_ai.tool.call": rawCallPayload,
        "gen_ai.tool.calls": rawCallsPayload,
    } = attributes;
    const callName = getStringAttribute(attributes, "gen_ai.tool.call.name");
    const toolName = getStringAttribute(attributes, "gen_ai.tool.name");
    if (callName !== undefined || toolName !== undefined || callArguments !== undefined) {
        calls.push({
            name: callName ?? toolName ?? "tool",
            arguments: stringifyValue(parseJsonValue(callArguments ?? {})),
        });
    }

    const callPayload = parseJsonValue(rawCallPayload);
    if (callPayload !== undefined) {
        const callEntry = normalizeToolCallEntry(callPayload);
        if (callEntry) {
            calls.push(callEntry);
        }
    }

    const callsPayload = parseJsonValue(rawCallsPayload);
    if (Array.isArray(callsPayload)) {
        for (const entry of callsPayload) {
            const callEntry = normalizeToolCallEntry(entry);
            if (callEntry) {
                calls.push(callEntry);
            }
        }
    }

    return calls;
};

const extractDetailedToolCallAttributes = (
    attributes: Record<string, unknown>,
): DetailedToolCall[] => {
    const calls: DetailedToolCall[] = [];
    const {
        "gen_ai.tool.call.arguments": callArguments,
        "gen_ai.tool.call": rawCallPayload,
        "gen_ai.tool.calls": rawCallsPayload,
    } = attributes;
    const callName = getStringAttribute(attributes, "gen_ai.tool.call.name");
    const toolName = getStringAttribute(attributes, "gen_ai.tool.name");
    const callId = getStringAttribute(attributes, "gen_ai.tool.call.id");
    if (callName !== undefined || toolName !== undefined || callArguments !== undefined) {
        calls.push({
            id: callId,
            name: callName ?? toolName ?? "tool",
            arguments: stringifyValue(parseJsonValue(callArguments ?? {})),
        });
    }

    const callPayload = parseJsonValue(rawCallPayload);
    if (callPayload !== undefined) {
        const callEntry = normalizeDetailedToolCallEntry(callPayload);
        if (callEntry) {
            calls.push(callEntry);
        }
    }

    const callsPayload = parseJsonValue(rawCallsPayload);
    if (Array.isArray(callsPayload)) {
        for (const entry of callsPayload) {
            const callEntry = normalizeDetailedToolCallEntry(entry);
            if (callEntry) {
                calls.push(callEntry);
            }
        }
    }

    return calls;
};

const extractAppChatToolInputAttributes = (
    attributes: Record<string, unknown>,
): { name: string; arguments: string }[] => {
    const input = attributes["app.chat.tool.input"];
    if (input === undefined) {
        return [];
    }
    return [
        {
            name: getStringAttribute(attributes, "app.chat.tool.name") ?? "tool",
            arguments: stringifyValue(parseJsonValue(input)),
        },
    ];
};

const extractAppChatToolResultAttributes = (
    attributes: Record<string, unknown>,
): { name: string; result: string }[] => {
    const result = attributes["app.chat.tool.result"];
    if (result === undefined) {
        return [];
    }
    return [
        {
            name: getStringAttribute(attributes, "app.chat.tool.name") ?? "tool",
            result: stringifyValue(parseJsonValue(result)),
        },
    ];
};

const extractToolResultAttributes = (
    attributes: Record<string, unknown>,
): { name: string; result: string }[] => {
    const results: { name: string; result: string }[] = [];
    const { "gen_ai.tool.call.result": rawCallResult } = attributes;
    const toolName =
        getStringAttribute(attributes, "gen_ai.tool.name") ??
        getStringAttribute(attributes, "gen_ai.tool.call.name");

    if (rawCallResult !== undefined) {
        const parsedResult = parseJsonValue(rawCallResult);
        if (isRecord(parsedResult)) {
            const entry = normalizeToolResultEntry(parsedResult);
            results.push(
                entry ?? {
                    name: toolName ?? "tool",
                    result: stringifyValue(parsedResult),
                },
            );
        } else {
            results.push({
                name: toolName ?? "tool",
                result: stringifyValue(parsedResult),
            });
        }
    }

    return results;
};

const normalizeMessages = (value: unknown): unknown[] => {
    const parsed = parseJsonValue(value);
    if (Array.isArray(parsed)) {
        return parsed;
    }
    if (isRecord(parsed)) {
        if (Array.isArray(parsed.messages)) {
            return parsed.messages;
        }
        if (parsed.message !== undefined) {
            return [parsed.message];
        }
        if (Array.isArray(parsed.choices)) {
            const choices: unknown[] = parsed.choices;
            return choices
                .map((choice): unknown => {
                    if (!isRecord(choice)) {
                        return choice;
                    }
                    const {message} = choice;
                    const {delta} = choice;
                    return message ?? delta ?? choice;
                })
                .filter((choice) => choice !== undefined);
        }
        if (Array.isArray(parsed.output)) {
            return parsed.output;
        }
    }
    return [];
};

const normalizeToolCalls = (value: unknown): unknown[] => {
    const parsed = parseJsonValue(value);
    if (Array.isArray(parsed)) {
        const fromMessages: unknown[] = [];
        for (const item of parsed) {
            if (isRecord(item)) {
                const { tool_calls: toolCalls, parts, message } = item;
                if (Array.isArray(toolCalls)) {
                    for (const call of toolCalls) {
                        fromMessages.push(call);
                    }
                }
                if (Array.isArray(parts)) {
                    for (const part of parts) {
                        if (isRecord(part)) {
                            const { type } = part;
                            if (type === "tool_call") {
                                fromMessages.push(part);
                            }
                        }
                    }
                }
                if (isRecord(message) && Array.isArray(message.tool_calls)) {
                    for (const call of message.tool_calls) {
                        fromMessages.push(call);
                    }
                }
                if (isRecord(message) && Array.isArray(message.parts)) {
                    for (const part of message.parts) {
                        if (isRecord(part)) {
                            const { type } = part;
                            if (type === "tool_call") {
                                fromMessages.push(part);
                            }
                        }
                    }
                }
            }
        }
        return fromMessages.length > 0 ? fromMessages : parsed;
    }
    if (isRecord(parsed)) {
        const { tool_calls: toolCalls, message, parts, choices } = parsed;
        if (Array.isArray(toolCalls)) {
            return toolCalls;
        }
        if (isRecord(message) && Array.isArray(message.tool_calls)) {
            return message.tool_calls;
        }
        if (Array.isArray(choices)) {
            const calls = choices.flatMap((choice): unknown[] => {
                if (!isRecord(choice)) {
                    return [];
                }
                const choiceMessage = choice.message;
                if (
                    !isRecord(choiceMessage) ||
                    !Array.isArray(choiceMessage.tool_calls)
                ) {
                    return [];
                }
                return choiceMessage.tool_calls as unknown[];
            });
            if (calls.length > 0) {
                return calls;
            }
        }
        if (Array.isArray(parts)) {
            return parts.filter((part) => {
                if (!isRecord(part)) {
                    return false;
                }
                const { type } = part;
                return type === "tool_call";
            });
        }
    }
    return [];
};

const buildToolCallMessagePart = (toolCall: unknown): TraceMessagePart => {
    const normalized = normalizeDetailedToolCallEntry(toolCall);
    return {
        type: "tool_call",
        content: normalized?.arguments ?? resolveMessageContent(toolCall),
        raw: toolCall,
    };
};

const getMessagePartKey = (part: TraceMessagePart): string => {
    if (part.type === "tool_call") {
        const normalized = normalizeDetailedToolCallEntry(part.raw);
        if (normalized !== undefined) {
            return `tool_call:${normalized.id ?? ""}:${normalized.name}:${normalized.arguments}`;
        }
    }
    return `${part.type}:${part.content ?? ""}:${resolveMessageContent(part.raw)}`;
};

const dedupeMessageParts = (parts: TraceMessagePart[]): TraceMessagePart[] => {
    const seen = new Set<string>();
    const deduped: TraceMessagePart[] = [];
    for (const part of parts) {
        const key = getMessagePartKey(part);
        if (!seen.has(key)) {
            seen.add(key);
            deduped.push(part);
        }
    }
    return deduped;
};

const extractMessages = (
    attributes: Record<string, unknown>,
    key: string,
): TraceMessage[] => {
    const raw = attributes[key];
    const items = normalizeMessages(raw);
    if (items.length === 0) {
        return [];
    }

    const messages: TraceMessage[] = [];
    for (const item of items) {
        if (isRecord(item)) {
            const {
                role: itemRole,
                content,
                text,
                message,
                data,
                parts,
                tool_calls: toolCalls,
            } = item;
            const role = typeof itemRole === "string" ? itemRole : "message";
            const normalizedParts = dedupeMessageParts([
                ...(parts === undefined ? [] : normalizeMessageParts(parts)),
                ...(Array.isArray(toolCalls)
                    ? toolCalls.map((toolCall) =>
                          buildToolCallMessagePart(toolCall),
                      )
                    : []),
            ]);
            const resolvedContent = resolveMessageContent(
                content ?? text ?? message ?? data ?? parts,
            );
            messages.push({
                role,
                content: resolvedContent,
                parts: normalizedParts.length > 0 ? normalizedParts : undefined,
            });
        }
    }
    return messages;
};

const extractToolCalls = (
    attributes: Record<string, unknown>,
    key: string,
): { name: string; arguments: string }[] => {
    const raw = attributes[key];
    const items = normalizeToolCalls(raw);
    if (items.length === 0) {
        return [];
    }

    const calls: { name: string; arguments: string }[] = [];
    for (const item of items) {
        const callEntry = normalizeToolCallEntry(item);
        if (callEntry) {
            calls.push(callEntry);
        }
    }
    return calls;
};

const extractDetailedToolCalls = (
    attributes: Record<string, unknown>,
    key: string,
): DetailedToolCall[] => {
    const raw = attributes[key];
    const items = normalizeToolCalls(raw);
    if (items.length === 0) {
        return [];
    }

    const calls: DetailedToolCall[] = [];
    for (const item of items) {
        const callEntry = normalizeDetailedToolCallEntry(item);
        if (callEntry) {
            calls.push(callEntry);
        }
    }
    return calls;
};

const extractToolMessageResults = (
    attributes: Record<string, unknown>,
    key: string,
): DetailedToolResult[] => {
    const raw = attributes[key];
    const items = normalizeMessages(raw);
    if (items.length === 0) {
        return [];
    }

    const results: DetailedToolResult[] = [];
    for (const item of items) {
        if (isRecord(item) && item.role === "tool") {
            const resultValue =
                item.content ??
                item.message ??
                item.data ??
                item.output ??
                item.result;
            if (resultValue !== undefined) {
                results.push({
                    id:
                        typeof item.tool_call_id === "string"
                            ? item.tool_call_id
                            : undefined,
                    name:
                        typeof item.name === "string" && item.name.trim() !== ""
                            ? item.name
                            : undefined,
                    result: stringifyValue(parseJsonValue(resultValue)),
                });
            }
        }
    }

    return results;
};

const extractToolMessageCalls = (
    attributes: Record<string, unknown>,
    key: string,
): DetailedToolCall[] => {
    const raw = attributes[key];
    const items = normalizeMessages(raw);
    if (items.length === 0) {
        return [];
    }

    const calls: DetailedToolCall[] = [];
    for (const item of items) {
        if (isRecord(item)) {
            if (Array.isArray(item.tool_calls)) {
                for (const toolCall of item.tool_calls) {
                    const normalized = normalizeDetailedToolCallEntry(toolCall);
                    if (normalized) {
                        calls.push(normalized);
                    }
                }
            }

            if (Array.isArray(item.parts)) {
                for (const part of item.parts) {
                    if (isRecord(part) && part.type === "tool_call") {
                        const normalized = normalizeDetailedToolCallEntry(part);
                        if (normalized) {
                            calls.push(normalized);
                        }
                    }
                }
            }
        }
    }

    return calls;
};

const firstNonEmpty = <T>(values: T[][]): T[] => {
    for (const value of values) {
        if (value.length > 0) {
            return value;
        }
    }
    return [];
};

export const extractRequestMessages = (
    attributes: Record<string, unknown>,
): { role: string; content: string }[] =>
    firstNonEmpty([
        extractMessages(attributes, "gen_ai.request.messages"),
        extractMessages(attributes, "gen_ai.input.messages"),
        extractMessages(attributes, "request_data"),
    ]);

export const extractResponseMessages = (
    attributes: Record<string, unknown>,
): { role: string; content: string }[] =>
    firstNonEmpty([
        extractMessages(attributes, "gen_ai.response.messages"),
        extractMessages(attributes, "gen_ai.output.messages"),
        extractMessages(attributes, "response_data"),
    ]);

export const extractResponseToolCalls = (
    attributes: Record<string, unknown>,
): { name: string; arguments: string }[] =>
    firstNonEmpty([
        extractToolCalls(attributes, "gen_ai.response.tool_calls"),
        extractToolCalls(attributes, "response_data"),
        extractToolCallAttributes(attributes),
    ]);

export const extractResponseToolCallDetails = (
    attributes: Record<string, unknown>,
): DetailedToolCall[] =>
    firstNonEmpty([
        extractDetailedToolCalls(attributes, "gen_ai.response.tool_calls"),
        extractDetailedToolCalls(attributes, "response_data"),
        extractDetailedToolCallAttributes(attributes),
    ]);

export const extractToolResults = (
    attributes: Record<string, unknown>,
): { name: string; result: string }[] =>
    firstNonEmpty([
        extractAppChatToolResultAttributes(attributes),
        extractToolResultAttributes(attributes),
    ]);

export const extractRequestToolResults = (
    attributes: Record<string, unknown>,
): DetailedToolResult[] =>
    firstNonEmpty([
        extractToolMessageResults(attributes, "gen_ai.request.messages"),
        extractToolMessageResults(attributes, "gen_ai.input.messages"),
        extractToolMessageResults(attributes, "request_data"),
    ]);

export const extractRequestToolCallDetails = (
    attributes: Record<string, unknown>,
): DetailedToolCall[] =>
    firstNonEmpty([
        extractToolMessageCalls(attributes, "gen_ai.request.messages"),
        extractToolMessageCalls(attributes, "gen_ai.input.messages"),
        extractToolMessageCalls(attributes, "request_data"),
    ]);

export const extractRequestTools = (
    attributes: Record<string, unknown>,
): { name: string; arguments: string }[] =>
    firstNonEmpty([
        extractAppChatToolInputAttributes(attributes),
        extractToolCalls(attributes, "gen_ai.request.tools"),
        extractToolCalls(attributes, "request_data"),
        extractToolCallAttributes(attributes),
    ]);
