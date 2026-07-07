import type {
    LoadingActivityLogEntry,
    LoadingToolState,
} from "@va/shared/types";

import {
    extractRequestToolCallDetails,
    extractRequestToolResults,
    extractResponseToolCallDetails,
    extractToolResults,
    getSpanEnd,
    getSpanStart,
    getStringAttribute,
    isRecord,
    parseJsonRecursively,
} from "../../traces/lib/trace-utils";
import type { TraceDetail, TraceSpan } from "../../traces/types";

const CHATBOT_AGENT_LABEL = "Chatbot agent";
const GUARDRAILS_AGENT_LABEL = "Guardrails agent";
const INVESTIGATION_AGENT_LABEL = "Investigation agent";

const AGENT_LABELS: Record<string, string> = {
    chatbot: CHATBOT_AGENT_LABEL,
    guardrails: GUARDRAILS_AGENT_LABEL,
    investigation: INVESTIGATION_AGENT_LABEL,
};

const ALLOWED_AGENT_NAMES = new Set(Object.keys(AGENT_LABELS));
const ANSWER_AGENT_LABELS = new Set([
    CHATBOT_AGENT_LABEL,
    INVESTIGATION_AGENT_LABEL,
]);

const normalizeAgentLabel = (agentName: string): string =>
    AGENT_LABELS[agentName] ?? agentName.replaceAll("_", " ");

const buildSpanLookup = (spans: TraceSpan[]): Map<string, TraceSpan> => {
    const lookup = new Map<string, TraceSpan>();
    for (const span of spans) {
        lookup.set(span.span_id, span);
    }
    return lookup;
};

const resolveAgentName = (
    span: TraceSpan,
    spanLookup: Map<string, TraceSpan>,
): string | undefined => {
    const direct = getStringAttribute(
        span.attributes ?? {},
        "gen_ai.agent.name",
    );
    if (direct !== undefined && direct.trim() !== "") {
        return ALLOWED_AGENT_NAMES.has(direct) ? direct : undefined;
    }

    let parentId: string | undefined = span.parent_span_id ?? undefined;
    const visited = new Set<string>();
    while (parentId !== undefined && parentId.trim() !== "") {
        if (visited.has(parentId)) {
            return undefined;
        }
        visited.add(parentId);
        const parent = spanLookup.get(parentId);
        if (parent === undefined) {
            return undefined;
        }
        const agentName = getStringAttribute(
            parent.attributes ?? {},
            "gen_ai.agent.name",
        );
        if (agentName !== undefined && agentName.trim() !== "") {
            return ALLOWED_AGENT_NAMES.has(agentName) ? agentName : undefined;
        }
        parentId = parent.parent_span_id ?? undefined;
    }
    return undefined;
};

const extractThinkingFromMessages = (value: unknown): string[] => {
    const parsed = parseJsonRecursively(value);
    if (!Array.isArray(parsed)) {
        return [];
    }
    const results: string[] = [];
    for (const message of parsed) {
        if (isRecord(message)) {
            const role =
                typeof message.role === "string" ? message.role : undefined;
            const roleMatches = role === undefined || role === "assistant";
            if (roleMatches && Array.isArray(message.parts)) {
                for (const part of message.parts) {
                    if (isRecord(part) && part.type === "thinking") {
                        const { content } = part;
                        if (
                            typeof content === "string" &&
                            content.trim() !== ""
                        ) {
                            results.push(content);
                        }
                    }
                }
            }
        }
    }
    return results;
};

const resolveReasoningParts = (
    attributes: Record<string, unknown>,
): string[] => {
    const parts: string[] = [];
    const candidates = [
        "gen_ai.response.reasoning",
        "gen_ai.response.reasoning_summary",
        "gen_ai.response.reasoning_text",
        "openai.response.reasoning",
        "openai.response.reasoning_summary",
        "openai.response.reasoning_text",
        "response.reasoning",
        "response.reasoning_summary",
    ];

    for (const key of candidates) {
        const value = attributes[key];
        if (typeof value === "string" && value.trim() !== "") {
            parts.push(value);
        }
    }

    const thinkingMessages = [
        "gen_ai.output.messages",
        "gen_ai.response.messages",
    ];
    for (const key of thinkingMessages) {
        const raw = attributes[key];
        if (raw !== undefined) {
            const thinkingParts = extractThinkingFromMessages(raw);
            for (const thinking of thinkingParts) {
                if (thinking.trim() !== "") {
                    parts.push(thinking);
                }
            }
        }
    }

    return parts;
};

const resolveDurationMs = (span: TraceSpan): number | undefined => {
    if (typeof span.duration_ms === "number") {
        return span.duration_ms;
    }
    const start = getSpanStart(span);
    const end = getSpanEnd(span);
    if (start === undefined || end === undefined) {
        return undefined;
    }
    return end - start;
};

const resolveToolState = (
    isError: boolean,
    hasOutput: boolean,
): LoadingToolState => {
    if (isError) {
        return "output-error";
    }
    if (hasOutput) {
        return "output-available";
    }
    return "input-available";
};

export const buildActivityLogFromTrace = (
    detail: TraceDetail,
): LoadingActivityLogEntry[] => {
    const { spans } = detail;
    if (spans.length === 0) {
        return [];
    }

    const spanLookup = buildSpanLookup(spans);
    const ordered = spans.toSorted((left, right) => {
        const leftStart = getSpanStart(left) ?? 0;
        const rightStart = getSpanStart(right) ?? 0;
        return leftStart - rightStart;
    });

    const entries: LoadingActivityLogEntry[] = [];
    const agentCounts = new Map<string, number>();
    const agentIdMap = new Map<string, string>();
    const pendingToolEntriesById = new Map<string, LoadingActivityLogEntry>();
    const pendingToolEntriesByName = new Map<
        string,
        LoadingActivityLogEntry[]
    >();
    const observedToolCallIds = new Set<string>();
    let sequence = 0;

    const shiftMapValue = <T>(
        map: Map<string, T[]>,
        key: string | undefined,
    ): T | undefined => {
        if (key === undefined || key.trim() === "") {
            return undefined;
        }

        const values = map.get(key);
        if (values === undefined || values.length === 0) {
            return undefined;
        }

        const value = values.shift();
        if (values.length === 0) {
            map.delete(key);
        }
        return value;
    };

    const pushMapValue = <T>(
        map: Map<string, T[]>,
        key: string,
        value: T,
    ): void => {
        const values = map.get(key) ?? [];
        values.push(value);
        map.set(key, values);
    };

    const applyToolResult = (
        entry: LoadingActivityLogEntry,
        toolOutput: unknown,
        options: {
            spanIsError: boolean;
            errorText?: string;
        },
    ): void => {
        entry.toolOutput = toolOutput;
        entry.toolState = resolveToolState(options.spanIsError, true);
        entry.status = options.spanIsError ? "error" : "complete";
        entry.toolErrorText = options.spanIsError
            ? options.errorText
            : undefined;
    };

    for (const span of ordered) {
        const attributes = span.attributes ?? {};
        const directAgent = getStringAttribute(attributes, "gen_ai.agent.name");
        if (
            directAgent !== undefined &&
            directAgent.trim() !== "" &&
            ALLOWED_AGENT_NAMES.has(directAgent)
        ) {
            const count = agentCounts.get(directAgent) ?? 0;
            agentCounts.set(directAgent, count + 1);
            const suffix = count === 0 ? "" : `:${count + 1}`;
            const agentId = `agent:${directAgent}${suffix}`;
            agentIdMap.set(directAgent, agentId);

            entries.push({
                id: agentId,
                sequence,
                label: normalizeAgentLabel(directAgent),
                status: "complete",
                kind: "agent",
                startedAtMs: getSpanStart(span),
                durationMs: resolveDurationMs(span),
            });
            sequence += 1;
        }

        const agentName = resolveAgentName(span, spanLookup);
        const parentId =
            agentName === undefined
                ? undefined
                : (agentIdMap.get(agentName) ?? undefined);

        const reasoningParts = resolveReasoningParts(attributes);
        if (agentName !== undefined && reasoningParts.length > 0) {
            for (const [index, reasoning] of reasoningParts.entries()) {
                if (reasoning.trim() !== "") {
                    entries.push({
                        id: `thinking:${span.span_id}:${index}`,
                        sequence,
                        label: `${normalizeAgentLabel(agentName)} reasoning`,
                        status: "complete",
                        kind: "thinking",
                        parentId,
                        thinkingContent: reasoning,
                    });
                    sequence += 1;
                }
            }
        }

        const toolCalls = extractResponseToolCallDetails(attributes);
        const toolResults = extractToolResults(attributes);
        const requestToolResults = extractRequestToolResults(attributes);
        const requestToolCalls = extractRequestToolCallDetails(attributes);
        const spanToolCallId = getStringAttribute(
            attributes,
            "gen_ai.tool.call.id",
        );
        const spanToolName =
            getStringAttribute(attributes, "gen_ai.tool.name") ??
            getStringAttribute(attributes, "gen_ai.tool.call.name");
        const spanToolArgs = attributes["gen_ai.tool.call.arguments"];
        const fallbackToolCalls =
            toolCalls.length > 0
                ? toolCalls.map((call) =>
                      spanToolName !== undefined && call.name === "tool"
                          ? { ...call, name: spanToolName }
                          : call,
                  )
                : spanToolName !== undefined && spanToolArgs !== undefined
                  ? [
                        {
                            id: spanToolCallId,
                            name: spanToolName,
                            arguments:
                                typeof spanToolArgs === "string"
                                    ? spanToolArgs
                                    : JSON.stringify(spanToolArgs),
                        },
                    ]
                  : [];

        if (
            fallbackToolCalls.length > 0 ||
            toolResults.length > 0 ||
            requestToolResults.length > 0
        ) {
            const resultsByName = new Map<string, string[]>();
            for (const result of toolResults) {
                pushMapValue(resultsByName, result.name, result.result);
            }

            const requestResultsById = new Map<string, string[]>();
            const requestResultsByName = new Map<string, string[]>();
            for (const result of requestToolResults) {
                if (result.id !== undefined && result.id.trim() !== "") {
                    pushMapValue(requestResultsById, result.id, result.result);
                }
                if (result.name !== undefined && result.name.trim() !== "") {
                    pushMapValue(
                        requestResultsByName,
                        result.name,
                        result.result,
                    );
                }
            }

            const requestCallsById = new Map<string, typeof requestToolCalls>();
            const requestCallsByName = new Map<
                string,
                typeof requestToolCalls
            >();
            for (const call of requestToolCalls) {
                if (call.id !== undefined && call.id.trim() !== "") {
                    pushMapValue(requestCallsById, call.id, call);
                }
                if (call.name.trim() !== "") {
                    pushMapValue(requestCallsByName, call.name, call);
                }
            }

            if (
                spanToolName !== undefined &&
                resultsByName.has("tool") &&
                !resultsByName.has(spanToolName)
            ) {
                const unnamed = resultsByName.get("tool") ?? [];
                resultsByName.delete("tool");
                resultsByName.set(spanToolName, unnamed);
            }

            if (
                spanToolName !== undefined &&
                requestResultsByName.has("tool") &&
                !requestResultsByName.has(spanToolName)
            ) {
                const unnamed = requestResultsByName.get("tool") ?? [];
                requestResultsByName.delete("tool");
                requestResultsByName.set(spanToolName, unnamed);
            }

            const spanIsError = span.status_code === "ERROR";
            const popPendingByName = (
                name: string,
            ): LoadingActivityLogEntry | undefined => {
                const list = pendingToolEntriesByName.get(name);
                if (list === undefined || list.length === 0) {
                    return undefined;
                }
                const entry = list.shift();
                if (list.length === 0) {
                    pendingToolEntriesByName.delete(name);
                }
                return entry;
            };

            const registerPendingEntry = (
                name: string,
                entry: LoadingActivityLogEntry,
                callId?: string,
            ): void => {
                if (callId !== undefined && callId.trim() !== "") {
                    pendingToolEntriesById.set(callId, entry);
                    return;
                }
                const list = pendingToolEntriesByName.get(name) ?? [];
                list.push(entry);
                pendingToolEntriesByName.set(name, list);
            };

            for (const [index, call] of fallbackToolCalls.entries()) {
                const results = resultsByName.get(call.name);
                const result = results?.shift();
                const isStructuredFinalResult =
                    call.name === "final_result" && result === undefined;
                const hasOutput = result !== undefined;
                const toolOutput =
                    result === undefined
                        ? undefined
                        : parseJsonRecursively(result);
                const toolInput = parseJsonRecursively(call.arguments);
                const toolState = isStructuredFinalResult
                    ? "output-available"
                    : resolveToolState(spanIsError, hasOutput);
                const callId =
                    call.id ??
                    (spanToolCallId !== undefined &&
                    spanToolCallId.trim() !== "" &&
                    fallbackToolCalls.length === 1
                        ? spanToolCallId
                        : undefined);
                if (callId !== undefined && callId.trim() !== "") {
                    observedToolCallIds.add(callId);
                }
                const requestResult =
                    shiftMapValue(requestResultsById, callId) ??
                    shiftMapValue(requestResultsByName, call.name);
                const resolvedToolOutput =
                    requestResult === undefined
                        ? toolOutput
                        : parseJsonRecursively(requestResult);
                const resolvedHasOutput =
                    requestResult !== undefined ||
                    hasOutput ||
                    isStructuredFinalResult;
                const existing =
                    callId === undefined
                        ? undefined
                        : pendingToolEntriesById.get(callId);

                if (existing) {
                    existing.toolInput = toolInput;
                    if (
                        resolvedToolOutput !== undefined ||
                        isStructuredFinalResult
                    ) {
                        existing.toolOutput = resolvedToolOutput;
                        existing.toolState = isStructuredFinalResult
                            ? "output-available"
                            : resolveToolState(spanIsError, true);
                        existing.status = spanIsError ? "error" : "complete";
                        existing.toolErrorText = spanIsError
                            ? (span.status_message ?? "Tool error")
                            : undefined;
                        if (callId !== undefined) {
                            pendingToolEntriesById.delete(callId);
                        }
                    }
                } else {
                    const entry: LoadingActivityLogEntry = {
                        id: `tool:${span.span_id}:${index}`,
                        sequence,
                        label: `Using tool: ${call.name}`,
                        status: spanIsError ? "error" : "complete",
                        kind: "tool",
                        parentId,
                        toolName: call.name,
                        toolInput,
                        toolOutput: resolvedToolOutput,
                        toolErrorText: spanIsError
                            ? (span.status_message ?? "Tool error")
                            : undefined,
                        toolState: resolvedHasOutput
                            ? resolveToolState(spanIsError, true)
                            : toolState,
                    };
                    entries.push(entry);
                    sequence += 1;

                    if (!resolvedHasOutput && !isStructuredFinalResult) {
                        registerPendingEntry(call.name, entry, callId);
                    }
                }
            }

            let resultIndex = fallbackToolCalls.length;
            for (const [name, values] of resultsByName.entries()) {
                for (const result of values) {
                    const toolOutput = parseJsonRecursively(result);
                    const entryById =
                        spanToolCallId === undefined
                            ? undefined
                            : pendingToolEntriesById.get(spanToolCallId);
                    const pendingEntry = entryById ?? popPendingByName(name);
                    if (pendingEntry) {
                        applyToolResult(pendingEntry, toolOutput, {
                            spanIsError,
                            errorText: span.status_message ?? "Tool error",
                        });
                        if (entryById && spanToolCallId !== undefined) {
                            pendingToolEntriesById.delete(spanToolCallId);
                        }
                    } else {
                        entries.push({
                            id: `tool:${span.span_id}:${resultIndex}`,
                            sequence,
                            label: `Using tool: ${name}`,
                            status: spanIsError ? "error" : "complete",
                            kind: "tool",
                            parentId,
                            toolName: name,
                            toolOutput,
                            toolErrorText: spanIsError
                                ? (span.status_message ?? "Tool error")
                                : undefined,
                            toolState: resolveToolState(spanIsError, true),
                        });
                        sequence += 1;
                        resultIndex += 1;
                    }
                }
            }

            for (const [callId, values] of requestResultsById.entries()) {
                for (const result of values) {
                    const toolOutput = parseJsonRecursively(result);
                    const pendingEntry = pendingToolEntriesById.get(callId);
                    if (pendingEntry) {
                        applyToolResult(pendingEntry, toolOutput, {
                            spanIsError,
                            errorText: span.status_message ?? "Tool error",
                        });
                        pendingToolEntriesById.delete(callId);
                    } else if (!observedToolCallIds.has(callId)) {
                        const requestCall = shiftMapValue(
                            requestCallsById,
                            callId,
                        );
                        const toolName = requestCall?.name ?? "tool";
                        const toolInput =
                            requestCall === undefined
                                ? undefined
                                : parseJsonRecursively(requestCall.arguments);

                        entries.push({
                            id: `tool:${span.span_id}:${resultIndex}`,
                            sequence,
                            label: `Using tool: ${toolName}`,
                            status: spanIsError ? "error" : "complete",
                            kind: "tool",
                            parentId,
                            toolName,
                            toolInput,
                            toolOutput,
                            toolErrorText: spanIsError
                                ? (span.status_message ?? "Tool error")
                                : undefined,
                            toolState: resolveToolState(spanIsError, true),
                        });
                        observedToolCallIds.add(callId);
                        sequence += 1;
                        resultIndex += 1;
                    }
                }
            }

            for (const [name, values] of requestResultsByName.entries()) {
                for (const result of values) {
                    const toolOutput = parseJsonRecursively(result);
                    const pendingEntry = popPendingByName(name);
                    if (pendingEntry) {
                        applyToolResult(pendingEntry, toolOutput, {
                            spanIsError,
                            errorText: span.status_message ?? "Tool error",
                        });
                    } else {
                        const requestCall = shiftMapValue(
                            requestCallsByName,
                            name,
                        );
                        const toolName = requestCall?.name ?? name;
                        const toolInput =
                            requestCall === undefined
                                ? undefined
                                : parseJsonRecursively(requestCall.arguments);

                        entries.push({
                            id: `tool:${span.span_id}:${resultIndex}`,
                            sequence,
                            label: `Using tool: ${toolName}`,
                            status: spanIsError ? "error" : "complete",
                            kind: "tool",
                            parentId,
                            toolName,
                            toolInput,
                            toolOutput,
                            toolErrorText: spanIsError
                                ? (span.status_message ?? "Tool error")
                                : undefined,
                            toolState: resolveToolState(spanIsError, true),
                        });
                        sequence += 1;
                        resultIndex += 1;
                    }
                }
            }
        }
    }

    return entries;
};

const normalizeSequence = (
    entries: LoadingActivityLogEntry[],
): LoadingActivityLogEntry[] =>
    entries.map((entry, index) => ({
        ...entry,
        sequence: index,
    }));

const toComparableValue = (value: unknown): string | undefined => {
    if (value === undefined) {
        return undefined;
    }

    return JSON.stringify(parseJsonRecursively(value));
};

const getFallbackParentId = (
    entries: LoadingActivityLogEntry[],
): string | undefined => {
    const answerAgentEntry = entries.find(
        (entry) => entry.kind === "agent" && ANSWER_AGENT_LABELS.has(entry.label),
    );
    if (answerAgentEntry !== undefined) {
        return answerAgentEntry.id;
    }

    return undefined;
};

const getFallbackInsertIndex = (entries: LoadingActivityLogEntry[]): number => {
    const answerAgentIndex = entries.findIndex(
        (entry) => entry.kind === "agent" && ANSWER_AGENT_LABELS.has(entry.label),
    );
    if (answerAgentIndex !== -1) {
        return answerAgentIndex + 1;
    }

    const guardrailsIndex = entries.findIndex(
        (entry) => entry.kind === "agent" && entry.label === GUARDRAILS_AGENT_LABEL,
    );
    if (guardrailsIndex !== -1) {
        return guardrailsIndex;
    }

    return entries.length;
};

const buildActivityLogFromStoredToolCalls = (
    storedToolCalls: unknown[] | undefined,
    options: {
        parentId: string | undefined;
        startingSequence: number;
    },
): LoadingActivityLogEntry[] => {
    if (storedToolCalls === undefined || storedToolCalls.length === 0) {
        return [];
    }

    const entries: LoadingActivityLogEntry[] = [];
    const pendingById = new Map<string, LoadingActivityLogEntry>();
    const pendingByName = new Map<string, LoadingActivityLogEntry[]>();
    let sequence = options.startingSequence;

    const registerPendingEntry = (
        toolName: string,
        entry: LoadingActivityLogEntry,
        toolCallId: string | undefined,
    ): void => {
        if (toolCallId !== undefined && toolCallId.trim() !== "") {
            pendingById.set(toolCallId, entry);
            return;
        }

        const pending = pendingByName.get(toolName) ?? [];
        pending.push(entry);
        pendingByName.set(toolName, pending);
    };

    const popPendingByName = (
        toolName: string,
    ): LoadingActivityLogEntry | undefined => {
        const pending = pendingByName.get(toolName);
        if (pending === undefined || pending.length === 0) {
            return undefined;
        }

        const entry = pending.shift();
        if (pending.length === 0) {
            pendingByName.delete(toolName);
        }
        return entry;
    };

    for (const item of storedToolCalls) {
        if (isRecord(item) && Array.isArray(item.tool_calls)) {
            for (const toolCall of item.tool_calls) {
                if (isRecord(toolCall)) {
                    const toolCallId =
                        typeof toolCall.id === "string"
                            ? toolCall.id
                            : undefined;
                    const toolFunction = isRecord(toolCall.function)
                        ? toolCall.function
                        : undefined;
                    const toolName =
                        typeof toolFunction?.name === "string" &&
                        toolFunction.name.trim() !== ""
                            ? toolFunction.name
                            : "tool";
                    const toolInput = parseJsonRecursively(
                        toolFunction?.arguments,
                    );

                    const entry: LoadingActivityLogEntry = {
                        id: `tool:metadata:${toolCallId ?? sequence}`,
                        sequence,
                        label: `Using tool: ${toolName}`,
                        status: "in_progress",
                        kind: "tool",
                        parentId: options.parentId,
                        toolName,
                        toolInput,
                        toolState: "input-available",
                    };
                    entries.push(entry);
                    sequence += 1;
                    registerPendingEntry(toolName, entry, toolCallId);
                }
            }
        }

        if (isRecord(item) && item.role === "tool") {
            const toolCallId =
                typeof item.tool_call_id === "string"
                    ? item.tool_call_id
                    : undefined;
            const toolName =
                typeof item.name === "string" ? item.name : undefined;
            const toolOutput = parseJsonRecursively(item.content);
            const pendingEntry =
                (toolCallId === undefined
                    ? undefined
                    : pendingById.get(toolCallId)) ??
                (toolName === undefined
                    ? undefined
                    : popPendingByName(toolName));

            if (pendingEntry === undefined) {
                const resolvedToolName =
                    toolName !== undefined && toolName.trim() !== ""
                        ? toolName
                        : "tool";
                entries.push({
                    id: `tool:metadata:${toolCallId ?? sequence}`,
                    sequence,
                    label: `Using tool: ${resolvedToolName}`,
                    status: "complete",
                    kind: "tool",
                    parentId: options.parentId,
                    toolName: resolvedToolName,
                    toolOutput,
                    toolState: "output-available",
                });
                sequence += 1;
            } else {
                pendingEntry.status = "complete";
                pendingEntry.toolState = "output-available";
                pendingEntry.toolOutput = toolOutput;
                if (toolCallId !== undefined) {
                    pendingById.delete(toolCallId);
                }
            }
        }
    }

    return entries;
};

export const mergeActivityLogWithStoredToolCalls = (
    activityLog: LoadingActivityLogEntry[],
    storedToolCalls: unknown[] | undefined,
): LoadingActivityLogEntry[] => {
    const normalizedActivityLog = activityLog.toSorted(
        (left, right) => left.sequence - right.sequence,
    );
    const fallbackEntries = buildActivityLogFromStoredToolCalls(
        storedToolCalls,
        {
            parentId: getFallbackParentId(normalizedActivityLog),
            startingSequence: normalizedActivityLog.length,
        },
    );

    if (fallbackEntries.length === 0) {
        return normalizedActivityLog;
    }

    if (normalizedActivityLog.length === 0) {
        return normalizeSequence(fallbackEntries);
    }

    const merged = [...normalizedActivityLog];
    const matchedIndexes = new Set<number>();
    let insertIndex = getFallbackInsertIndex(merged);

    for (const fallbackEntry of fallbackEntries) {
        const fallbackInput = toComparableValue(fallbackEntry.toolInput);
        let matchedIndex = -1;

        for (const [index, existingEntry] of merged.entries()) {
            const sameTool =
                !matchedIndexes.has(index) &&
                existingEntry.kind === "tool" &&
                existingEntry.toolName === fallbackEntry.toolName;

            if (sameTool) {
                const existingInput = toComparableValue(
                    existingEntry.toolInput,
                );
                const hasMatchingComparableInput =
                    fallbackInput === undefined ||
                    existingInput === undefined ||
                    fallbackInput === existingInput;

                if (hasMatchingComparableInput) {
                    matchedIndex = index;
                    break;
                }
            }
        }

        const hasMatchedEntry = matchedIndex !== -1;
        if (hasMatchedEntry) {
            const existingEntry = merged[matchedIndex];
            matchedIndexes.add(matchedIndex);

            const hasFallbackOutput = fallbackEntry.toolOutput !== undefined;
            const hasExistingOutput = existingEntry.toolOutput !== undefined;
            const nextStatus =
                existingEntry.status === "error"
                    ? existingEntry.status
                    : hasFallbackOutput
                      ? fallbackEntry.status
                      : existingEntry.status;

            merged[matchedIndex] = {
                ...existingEntry,
                parentId: existingEntry.parentId ?? fallbackEntry.parentId,
                toolInput: existingEntry.toolInput ?? fallbackEntry.toolInput,
                toolOutput: hasExistingOutput
                    ? existingEntry.toolOutput
                    : fallbackEntry.toolOutput,
                toolErrorText:
                    existingEntry.toolErrorText ?? fallbackEntry.toolErrorText,
                toolState:
                    existingEntry.toolState === "output-available" ||
                    existingEntry.toolState === "output-error"
                        ? existingEntry.toolState
                        : (fallbackEntry.toolState ?? existingEntry.toolState),
                status: nextStatus,
            };
        } else {
            merged.splice(insertIndex, 0, fallbackEntry);
            insertIndex += 1;
        }
    }

    return normalizeSequence(merged);
};
