import {
    extractRequestMessages,
    extractResponseMessages,
    extractResponseToolCalls,
    extractToolResults,
    getResolvedSpanTiming,
    getSpanEnd,
    getSpanStart,
    getStringAttribute,
    type TraceMessage,
    type TraceMessagePart,
} from "../lib/trace-utils";
import {
    formatSpanDuration,
    getSpanTimelineLayout,
} from "../lib/trace-view-utils";
import type { TraceSpan } from "../types";
import { stringifyValue } from "./trace-turn-content-utils";
import {
    formatNumeric,
    formatOffsetMs,
    getNumericAttribute,
} from "./trace-turn-metrics-utils";

interface TimingRow {
    spanId: string;
    label: string;
    value: string;
    offsetPct: number;
    widthPct: number;
    barClass: string;
    start: number;
    depth: number;
    displaySpan: TraceSpan;
    detailSpan: TraceSpan;
    metricSpans: TraceSpan[];
    contentSpans: TraceSpan[];
}

interface SpanOverviewSelection {
    headerRows: { label: string; value: string }[];
    systemInstructions?: string;
    requestLabel?: string;
    responseLabel?: string;
    requestMessages: TraceMessage[];
    responseMessages: TraceMessage[];
    hasSummaryContent: boolean;
    showToolName: boolean;
    isEmbeddings: boolean;
}

interface SpanOverviewModel {
    timingRows: TimingRow[];
    selection?: SpanOverviewSelection;
}

const parseJsonAttribute = (value: unknown): unknown => {
    if (typeof value !== "string") {
        return value;
    }
    try {
        return JSON.parse(value) as unknown;
    } catch {
        return value;
    }
};

const resolveAttributeValue = (
    attributes: Record<string, unknown>,
    keys: string[],
): unknown => {
    for (const key of keys) {
        const value = attributes[key];
        const hasValue =
            value !== undefined &&
            value !== null &&
            (typeof value !== "string" || value.trim() !== "");
        if (hasValue) {
            return value;
        }
    }
    return undefined;
};

const firstNonEmptyFromSpans = <T>(
    spans: TraceSpan[],
    selector: (attributes: Record<string, unknown>) => T[],
): T[] => {
    for (const span of spans) {
        const values = selector(span.attributes ?? {});
        if (values.length > 0) {
            return values;
        }
    }
    return [];
};

const firstStringAttributeFromSpans = (
    spans: TraceSpan[],
    keys: string[],
): string | undefined => {
    for (const span of spans) {
        const attributes = span.attributes ?? {};
        for (const key of keys) {
            const value = getStringAttribute(attributes, key);
            if (value !== undefined && value.trim() !== "") {
                return value;
            }
        }
    }
    return undefined;
};

const buildTokenSummary = (
    inputTokens: number | undefined,
    cacheTokens: number | undefined,
    outputTokens: number | undefined,
    isLlm: boolean,
): string | undefined => {
    const parts: string[] = [];
    if (inputTokens !== undefined) {
        parts.push(`input ${formatNumeric(inputTokens)}`);
    }
    if (isLlm && cacheTokens !== undefined) {
        parts.push(`cache ${formatNumeric(cacheTokens)}`);
    }
    if (isLlm && outputTokens !== undefined) {
        parts.push(`output ${formatNumeric(outputTokens)}`);
    }
    return parts.length > 0 ? parts.join(" • ") : undefined;
};

const buildChildrenByParent = (
    spans: TraceSpan[],
): Map<string, TraceSpan[]> => {
    const childrenByParent = new Map<string, TraceSpan[]>();
    for (const span of spans) {
        const parentId = span.parent_span_id;
        if (typeof parentId === "string" && parentId.trim() !== "") {
            const children = childrenByParent.get(parentId) ?? [];
            children.push(span);
            childrenByParent.set(parentId, children);
        }
    }
    return childrenByParent;
};

const getDirectAgentName = (span: TraceSpan): string | undefined => {
    const agentName = getStringAttribute(
        span.attributes ?? {},
        "gen_ai.agent.name",
    );
    return agentName !== undefined && agentName.trim() !== ""
        ? agentName
        : undefined;
};

const resolveAgentName = (
    span: TraceSpan,
    spanLookup: Map<string, TraceSpan>,
): string | undefined => {
    const directAgentName = getDirectAgentName(span);
    if (directAgentName !== undefined) {
        return directAgentName;
    }

    let parentId: string | undefined = span.parent_span_id ?? undefined;
    const visited = new Set<string>();
    while (typeof parentId === "string" && parentId.trim() !== "") {
        if (visited.has(parentId)) {
            return undefined;
        }
        visited.add(parentId);
        const parent = spanLookup.get(parentId);
        if (parent === undefined) {
            return undefined;
        }

        const parentAgentName = getDirectAgentName(parent);
        if (parentAgentName !== undefined) {
            return parentAgentName;
        }
        parentId = parent.parent_span_id ?? undefined;
    }
    return undefined;
};

const hasToolAttributes = (attributes: Record<string, unknown>): boolean =>
    attributes["app.chat.tool.name"] !== undefined ||
    attributes["app.chat.tool.input"] !== undefined ||
    attributes["app.chat.tool.result"] !== undefined ||
    attributes["gen_ai.tool.name"] !== undefined ||
    attributes["gen_ai.tool.call"] !== undefined ||
    attributes["gen_ai.tool.calls"] !== undefined ||
    attributes["gen_ai.tool.call.name"] !== undefined ||
    attributes["gen_ai.tool.call.arguments"] !== undefined ||
    attributes["gen_ai.tool.call.result"] !== undefined;

const hasRequestOrResponseContent = (span: TraceSpan): boolean => {
    const attributes = span.attributes ?? {};
    const hasResponseText =
        getStringAttribute(attributes, "gen_ai.response.text") !== undefined ||
        getStringAttribute(attributes, "gen_ai.response.message") !== undefined;

    return (
        extractRequestMessages(attributes).length > 0 ||
        extractResponseMessages(attributes).length > 0 ||
        extractResponseToolCalls(attributes).length > 0 ||
        extractToolResults(attributes).length > 0 ||
        hasResponseText ||
        hasToolAttributes(attributes)
    );
};

const getSortedDescendants = (
    spanId: string,
    childrenByParent: Map<string, TraceSpan[]>,
): TraceSpan[] => {
    const descendants: TraceSpan[] = [];
    const queue = [...(childrenByParent.get(spanId) ?? [])];

    while (queue.length > 0) {
        const span = queue.shift();
        if (span !== undefined) {
            descendants.push(span);
            queue.push(...(childrenByParent.get(span.span_id) ?? []));
        }
    }

    return descendants.toSorted((left, right) => {
        const leftStart = getResolvedSpanTiming(left).start ?? 0;
        const rightStart = getResolvedSpanTiming(right).start ?? 0;
        return leftStart - rightStart;
    });
};

const pickRepresentativeDetailSpan = (
    displaySpan: TraceSpan,
    descendants: TraceSpan[],
): TraceSpan => {
    const descendantsWithContent = descendants.filter((span) =>
        hasRequestOrResponseContent(span),
    );
    const descendantsWithModel = descendants.filter((span) => {
        const requestModel = getStringAttribute(
            span.attributes ?? {},
            "gen_ai.request.model",
        );
        return requestModel !== undefined && requestModel.trim() !== "";
    });

    return (
        descendantsWithContent.at(-1) ??
        descendantsWithModel.at(-1) ??
        displaySpan
    );
};

const isStreamingSummaryLog = (span: TraceSpan): boolean =>
    span.attributes?.["logfire.span_type"] === "log" &&
    span.name.startsWith("streaming response from ");

const isUrlGuardrailsSpan = (span: TraceSpan): boolean => span.name === "url_guardrails";

const getOperationName = (span: TraceSpan): string | undefined =>
    getStringAttribute(span.attributes ?? {}, "gen_ai.operation.name");

const isLlmOperationSpan = (span: TraceSpan): boolean => {
    const operationName = getOperationName(span);
    return operationName !== undefined && operationName !== "embeddings";
};

const getRowColorForAgent = (agentName: string | undefined): string => {
    switch (agentName) {
        case "search": {
            return "bg-chart-2";
        }
        case "guardrails": {
            return "bg-chart-4";
        }
        case "chatbot": {
            return "bg-chart-1";
        }
        default: {
            return "bg-primary";
        }
    }
};

const getRawSpanBounds = (
    span: TraceSpan,
): {
    earliest: number | undefined;
    latest: number | undefined;
    target: number | undefined;
} => {
    const rawStart = getSpanStart(span);
    const rawEnd = getSpanEnd(span);

    if (rawStart === undefined && rawEnd === undefined) {
        return {
            earliest: undefined,
            latest: undefined,
            target: undefined,
        };
    }

    if (rawStart === undefined) {
        return {
            earliest: rawEnd,
            latest: rawEnd,
            target: rawEnd,
        };
    }

    if (rawEnd === undefined) {
        return {
            earliest: rawStart,
            latest: rawStart,
            target: rawStart,
        };
    }

    return {
        earliest: Math.min(rawStart, rawEnd),
        latest: Math.max(rawStart, rawEnd),
        target: rawEnd,
    };
};

const buildSyntheticSpanFromBounds = (
    span: TraceSpan,
    startTimeMs: number,
    endTimeMs: number,
): TraceSpan => ({
    ...span,
    duration_ms: Math.max(endTimeMs - startTimeMs, 0),
    end_time: new Date(endTimeMs).toISOString(),
    start_time: new Date(startTimeMs).toISOString(),
});

const normalizeOperationLabel = (span: TraceSpan): string => {
    if (span.name.startsWith("create embedding for ")) {
        return "Embedding lookup";
    }
    if (span.name.startsWith("retrieve documents:")) {
        return "Retrieve documents";
    }
    if (span.name.includes("list_website_")) {
        return span.name.replaceAll("_", " ");
    }
    return span.name.replaceAll("_", " ");
};

const classifyStandaloneLlm = (
    span: TraceSpan,
): "title" | "summary" | undefined => {
    const attributes = span.attributes ?? {};
    const filepath = getStringAttribute(attributes, "code.filepath");
    const functionName = getStringAttribute(attributes, "code.function");

    if (
        functionName === "_run_title_prompt" ||
        filepath?.endsWith("/app/chat/title.py") === true ||
        filepath?.endsWith("app/chat/title.py") === true
    ) {
        return "title";
    }

    if (
        functionName === "_generate_internal_summary" ||
        filepath?.endsWith("/app/chat/internal_summary.py") === true ||
        filepath?.endsWith("app/chat/internal_summary.py") === true
    ) {
        return "summary";
    }

    return undefined;
};

const sumNumericAttributes = (
    spans: TraceSpan[],
    key: string,
): number | undefined => {
    let total = 0;
    let seen = false;

    for (const span of spans) {
        const value = getNumericAttribute(span.attributes ?? {}, key);
        if (value !== undefined) {
            total += value;
            seen = true;
        }
    }

    return seen ? total : undefined;
};

const hasUsageMetrics = (span: TraceSpan): boolean => {
    const attributes = span.attributes ?? {};
    return (
        getNumericAttribute(attributes, "gen_ai.usage.input_tokens") !==
            undefined ||
        getNumericAttribute(
            attributes,
            "gen_ai.usage.cache_read.input_tokens",
        ) !== undefined ||
        getNumericAttribute(attributes, "gen_ai.usage.output_tokens") !==
            undefined ||
        getNumericAttribute(attributes, "operation.cost") !== undefined ||
        getStringAttribute(attributes, "app.llm_response_metrics") !== undefined
    );
};

const parseLlmResponseMetrics = (
    span: TraceSpan,
): {
    requestIndex?: number;
    inputTokens?: number;
    cacheReadTokens?: number;
    outputTokens?: number;
    cost?: number;
}[] => {
    const raw = getStringAttribute(
        span.attributes ?? {},
        "app.llm_response_metrics",
    );
    if (raw === undefined) {
        return [];
    }

    try {
        const parsed = JSON.parse(raw) as unknown;
        if (!Array.isArray(parsed)) {
            return [];
        }

        return parsed
            .filter(
                (item): item is Record<string, unknown> =>
                    typeof item === "object" && item !== null,
            )
            .map((item) => ({
                requestIndex: getNumericAttribute(item, "request_index"),
                inputTokens: getNumericAttribute(item, "input_tokens"),
                cacheReadTokens: getNumericAttribute(item, "cache_read_tokens"),
                outputTokens: getNumericAttribute(item, "output_tokens"),
                cost: getNumericAttribute(item, "cost"),
            }));
    } catch {
        return [];
    }
};

const buildMetricSpan = (
    span: TraceSpan,
    metric: {
        inputTokens?: number;
        cacheReadTokens?: number;
        outputTokens?: number;
        cost?: number;
    },
): TraceSpan => {
    const attributes: Record<string, unknown> =
        span.attributes === null ? {} : { ...span.attributes };
    attributes["gen_ai.operation.name"] = "chat";

    if (metric.inputTokens !== undefined) {
        attributes["gen_ai.usage.input_tokens"] = metric.inputTokens;
    }
    if (metric.cacheReadTokens !== undefined) {
        attributes["gen_ai.usage.cache_read.input_tokens"] =
            metric.cacheReadTokens;
    }
    if (metric.outputTokens !== undefined) {
        attributes["gen_ai.usage.output_tokens"] = metric.outputTokens;
    }
    if (metric.cost !== undefined) {
        attributes["operation.cost"] = metric.cost;
    }

    return {
        ...span,
        attributes,
    };
};

const createTimingRow = ({
    depth,
    detailSpan,
    displaySpan,
    label,
    rangeEnd,
    rangeStart,
    barClass,
    metricSpans,
    contentSpans,
}: {
    depth: number;
    detailSpan: TraceSpan;
    displaySpan: TraceSpan;
    label: string;
    rangeEnd: number | undefined;
    rangeStart: number | undefined;
    barClass: string;
    metricSpans?: TraceSpan[];
    contentSpans?: TraceSpan[];
}): TimingRow | undefined => {
    const timelineLayout = getSpanTimelineLayout(
        displaySpan,
        rangeStart,
        rangeEnd,
    );
    if (timelineLayout === undefined) {
        return undefined;
    }

    return {
        spanId: displaySpan.span_id,
        label,
        value: formatSpanDuration(displaySpan),
        offsetPct: timelineLayout.offsetPct,
        widthPct: timelineLayout.widthPct,
        barClass,
        start: timelineLayout.start,
        depth,
        displaySpan,
        detailSpan,
        metricSpans: metricSpans ?? [detailSpan],
        contentSpans: contentSpans ?? [detailSpan],
    };
};

const buildTimingRows = (
    sourceSpans: TraceSpan[],
    rangeStart: number | undefined,
    rangeDuration: number | undefined,
): TimingRow[] => {
    const childrenByParent = buildChildrenByParent(sourceSpans);
    const spanLookup = new Map(sourceSpans.map((span) => [span.span_id, span]));
    const rangeEnd =
        rangeStart !== undefined && rangeDuration !== undefined
            ? rangeStart + rangeDuration
            : undefined;
    const sortedSpans = sourceSpans.toSorted((left, right) => {
        const leftStart = getResolvedSpanTiming(left).start ?? 0;
        const rightStart = getResolvedSpanTiming(right).start ?? 0;
        return leftStart - rightStart;
    });
    const standaloneCategoryTotals = {
        summary: sortedSpans.filter(
            (span) => classifyStandaloneLlm(span) === "summary",
        ).length,
        title: sortedSpans.filter(
            (span) => classifyStandaloneLlm(span) === "title",
        ).length,
    };

    let searchCount = 0;
    let chatbotCount = 0;
    let guardrailsCount = 0;
    let titleCount = 0;
    let summaryCount = 0;
    const rows: TimingRow[] = [];

    for (const span of sortedSpans) {
        const isTurnSpan = span.name.includes("handle_conversation_turn");
        const directAgentName = getDirectAgentName(span);
        const isAgentParent =
            directAgentName !== undefined && span.name.startsWith("chat ");

        if (isTurnSpan) {
            const row = createTimingRow({
                depth: 0,
                detailSpan: span,
                displaySpan: span,
                label: "Turn",
                rangeEnd,
                rangeStart,
                barClass: "bg-primary",
            });
            if (row !== undefined) {
                rows.push(row);
            }
        } else if (isAgentParent) {
            let label = span.name;
            switch (directAgentName) {
                case "search": {
                    searchCount += 1;
                    label =
                        searchCount > 1 ? `Search #${searchCount}` : "Search";
                    break;
                }
                case "chatbot": {
                    chatbotCount += 1;
                    label = `Chatbot Attempt #${chatbotCount}`;
                    break;
                }
                case "guardrails": {
                    guardrailsCount += 1;
                    label = `Guardrails #${guardrailsCount}`;
                    break;
                }
                default: {
                    break;
                }
            }

            const descendants = getSortedDescendants(
                span.span_id,
                childrenByParent,
            );
            const llmResponseMetrics = parseLlmResponseMetrics(span);
            const parentRow = createTimingRow({
                depth: 0,
                detailSpan: pickRepresentativeDetailSpan(span, descendants),
                displaySpan: span,
                label,
                rangeEnd,
                rangeStart,
                barClass: getRowColorForAgent(directAgentName),
                metricSpans: hasUsageMetrics(span) ? [span] : descendants,
            });
            if (parentRow !== undefined) {
                rows.push(parentRow);
            }

            const directChildren = (
                childrenByParent.get(span.span_id) ?? []
            ).toSorted((left, right) => {
                const leftStart = getResolvedSpanTiming(left).start ?? 0;
                const rightStart = getResolvedSpanTiming(right).start ?? 0;
                return leftStart - rightStart;
            });
            let llmCount = 0;

            let llmPhaseSpans: TraceSpan[] = [];
            let llmPhaseStreamingLogs: TraceSpan[] = [];

            const flushLlmPhase = (): void => {
                if (llmPhaseSpans.length === 0) {
                    return;
                }

                const phaseBounds = llmPhaseSpans
                    .map((candidate) => getRawSpanBounds(candidate))
                    .filter(
                        (
                            candidate,
                        ): candidate is {
                            earliest: number;
                            latest: number;
                            target: number | undefined;
                        } =>
                            candidate.earliest !== undefined &&
                            candidate.latest !== undefined,
                    );
                if (phaseBounds.length === 0) {
                    llmPhaseSpans = [];
                    llmPhaseStreamingLogs = [];
                    return;
                }

                llmCount += 1;

                const phaseStart = Math.min(
                    ...phaseBounds.map((candidate) => candidate.earliest),
                );
                const phaseEndCandidates = [
                    ...phaseBounds.map((candidate) => candidate.latest),
                    ...llmPhaseStreamingLogs
                        .map(
                            (candidate) =>
                                getResolvedSpanTiming(candidate).end ??
                                getResolvedSpanTiming(candidate).start,
                        )
                        .filter(
                            (candidate): candidate is number =>
                                candidate !== undefined,
                        ),
                ];
                const phaseEnd = Math.max(...phaseEndCandidates);
                const detailSpan = llmPhaseSpans.at(-1) ?? llmPhaseSpans[0];
                const llmMetric = llmResponseMetrics[llmCount - 1];
                const row = createTimingRow({
                    depth: 1,
                    detailSpan,
                    displaySpan: buildSyntheticSpanFromBounds(
                        detailSpan,
                        phaseStart,
                        phaseEnd,
                    ),
                    label: `LLM #${llmCount}`,
                    rangeEnd,
                    rangeStart,
                    barClass: getRowColorForAgent(directAgentName),
                    metricSpans:
                        llmMetric === undefined
                            ? llmPhaseSpans
                            : [buildMetricSpan(detailSpan, llmMetric)],
                    contentSpans: [
                        ...llmPhaseSpans,
                        ...llmPhaseStreamingLogs,
                    ],
                });
                if (row !== undefined) {
                    rows.push(row);
                }

                llmPhaseSpans = [];
                llmPhaseStreamingLogs = [];
            };

            for (const child of directChildren) {
                if (isStreamingSummaryLog(child)) {
                    if (llmPhaseSpans.length > 0) {
                        llmPhaseStreamingLogs.push(child);
                    }
                } else if (isLlmOperationSpan(child)) {
                    llmPhaseSpans.push(child);
                } else {
                    flushLlmPhase();

                    const row = createTimingRow({
                        depth: 1,
                        detailSpan: child,
                        displaySpan: child,
                        label: isUrlGuardrailsSpan(child)
                            ? "URL Guardrails"
                            : normalizeOperationLabel(child),
                        rangeEnd,
                        rangeStart,
                        barClass: isUrlGuardrailsSpan(child)
                            ? "bg-chart-4"
                            : getOperationName(child) === "embeddings"
                              ? "bg-chart-3"
                              : "bg-chart-5",
                    });
                    if (row !== undefined) {
                        rows.push(row);
                    }
                }
            }

            flushLlmPhase();
        } else {
            const agentName = resolveAgentName(span, spanLookup);
            const isStandaloneLlm =
                isLlmOperationSpan(span) && agentName === undefined;
            if (isStandaloneLlm) {
                const standaloneCategory = classifyStandaloneLlm(span);
                let label = span.name;
                if (standaloneCategory === "title") {
                    titleCount += 1;
                    label =
                        standaloneCategoryTotals.title > 1
                            ? `Title generation #${titleCount}`
                            : "Title generation";
                } else if (standaloneCategory === "summary") {
                    summaryCount += 1;
                    label =
                        standaloneCategoryTotals.summary > 1
                            ? `Summary generation #${summaryCount}`
                            : "Summary generation";
                }
                const row = createTimingRow({
                    depth: 0,
                    detailSpan: span,
                    displaySpan: span,
                    label,
                    rangeEnd,
                    rangeStart,
                    barClass: "bg-chart-1",
                });
                if (row !== undefined) {
                    rows.push(row);
                }
            }
        }
    }

    const rowSpanIds = new Set(rows.map((row) => row.spanId));
    for (const span of sortedSpans) {
        if (isUrlGuardrailsSpan(span) && !rowSpanIds.has(span.span_id)) {
            const row = createTimingRow({
                depth: 1,
                detailSpan: span,
                displaySpan: span,
                label: "URL Guardrails",
                rangeEnd,
                rangeStart,
                barClass: "bg-chart-4",
            });
            if (row !== undefined) {
                rows.push(row);
                rowSpanIds.add(row.spanId);
            }
        }
    }

    return rows.toSorted((left, right) => left.start - right.start);
};

export const buildSpanOverviewModel = ({
    spans,
    traceStart,
    traceEnd,
    selectedSpanId,
}: {
    spans: TraceSpan[];
    traceStart: number | undefined;
    traceEnd: number | undefined;
    selectedSpanId: string | undefined;
}): SpanOverviewModel => {
    const overallRangeStart = traceStart;
    const overallRangeDuration =
        traceStart !== undefined && traceEnd !== undefined
            ? traceEnd - traceStart
            : undefined;

    const timingRows = buildTimingRows(
        spans,
        overallRangeStart,
        overallRangeDuration,
    );

    const selectedTimingRow =
        selectedSpanId === undefined
            ? undefined
            : timingRows.find((row) => row.spanId === selectedSpanId);
    const selectedDisplaySpan = selectedTimingRow?.displaySpan;
    const selectedDetailSpan = selectedTimingRow?.detailSpan;
    const selectedMetricSpans =
        selectedTimingRow?.metricSpans ??
        (selectedDetailSpan === undefined ? [] : [selectedDetailSpan]);
    const selectedContentSpans =
        selectedTimingRow?.contentSpans ??
        (selectedDetailSpan === undefined ? [] : [selectedDetailSpan]);
    const selectedTimingAttributes = selectedDetailSpan?.attributes ?? {};
    const selectedSpanLabel = selectedTimingRow?.label;
    const selectedSpanDuration =
        selectedDisplaySpan === undefined
            ? undefined
            : formatSpanDuration(selectedDisplaySpan);
    const selectedInputTokens = sumNumericAttributes(
        selectedMetricSpans,
        "gen_ai.usage.input_tokens",
    );
    const selectedOutputTokens = sumNumericAttributes(
        selectedMetricSpans,
        "gen_ai.usage.output_tokens",
    );
    const selectedCacheTokens = sumNumericAttributes(
        selectedMetricSpans,
        "gen_ai.usage.cache_read.input_tokens",
    );
    const selectedSpanStart =
        selectedDisplaySpan === undefined
            ? undefined
            : getResolvedSpanTiming(selectedDisplaySpan).start;
    const selectedOffsetMs =
        traceStart !== undefined && selectedSpanStart !== undefined
            ? selectedSpanStart - traceStart
            : undefined;
    const selectedOperationNames = [
        ...new Set(
            selectedMetricSpans
                .map((span) =>
                    getStringAttribute(
                        span.attributes ?? {},
                        "gen_ai.operation.name",
                    ),
                )
                .filter(
                    (value): value is string =>
                        value !== undefined && value.trim() !== "",
                ),
        ),
    ];
    const hasSelectedOperation = selectedOperationNames.length > 0;
    const selectedIsEmbeddings =
        hasSelectedOperation &&
        selectedOperationNames.every((value) => value === "embeddings");
    const selectedIsLlm =
        hasSelectedOperation &&
        selectedOperationNames.every((value) => value !== "embeddings");
    const shouldShowTokens = selectedIsLlm || selectedIsEmbeddings;
    const selectedTokenSummary =
        selectedDetailSpan === undefined || !shouldShowTokens
            ? undefined
            : buildTokenSummary(
                  selectedInputTokens,
                  selectedCacheTokens,
                  selectedOutputTokens,
                  selectedIsLlm,
              );
    const selectedPrompt = resolveAttributeValue(selectedTimingAttributes, [
        "gen_ai.request.prompt",
    ]);
    const selectedSystemInstructions = firstStringAttributeFromSpans(
        selectedContentSpans,
        ["gen_ai.system_instructions"],
    );
    const selectedEmbeddingInput = resolveAttributeValue(
        selectedTimingAttributes,
        [
            "inputs",
            "gen_ai.request.text",
            "gen_ai.request.input",
            "gen_ai.request.prompt",
        ],
    );
    const selectedRequestMessages = firstNonEmptyFromSpans(
        selectedContentSpans,
        extractRequestMessages,
    );
    const selectedResponseMessages = firstNonEmptyFromSpans(
        selectedContentSpans,
        extractResponseMessages,
    );
    const selectedResponseText = firstStringAttributeFromSpans(
        selectedContentSpans,
        ["gen_ai.response.text", "gen_ai.response.message"],
    );
    const selectedToolCalls = firstNonEmptyFromSpans(
        selectedContentSpans,
        extractResponseToolCalls,
    );
    const selectedToolResults = firstNonEmptyFromSpans(
        selectedContentSpans,
        extractToolResults,
    );
    const selectedUrlGuardrailsAttributes =
        selectedContentSpans.find((span) => isUrlGuardrailsSpan(span))?.attributes ?? undefined;
    const selectedUrlGuardrailsMessage =
        selectedUrlGuardrailsAttributes === undefined
            ? undefined
            : {
                  role: "url_guardrails",
                  content: stringifyValue({
                      is_valid:
                          selectedUrlGuardrailsAttributes[
                              "app.guardrails.url.is_valid"
                          ],
                      blog_urls: parseJsonAttribute(
                          selectedUrlGuardrailsAttributes[
                              "app.guardrails.url.blog_urls"
                          ],
                      ),
                      unknown_urls: parseJsonAttribute(
                          selectedUrlGuardrailsAttributes[
                              "app.guardrails.url.unknown_urls"
                          ],
                      ),
                  }),
              };
    const selectedHasUrlGuardrails = selectedUrlGuardrailsMessage !== undefined;
    const selectedHasTools =
        hasToolAttributes(selectedTimingAttributes) ||
        selectedToolCalls.length > 0 ||
        selectedToolResults.length > 0;
    const buildToolCallParts = (): TraceMessagePart[] =>
        selectedToolCalls.map((call) => ({
            type: "tool_call",
            content: call.arguments,
            raw: {
                name: call.name,
                arguments: call.arguments,
            },
        }));
    const buildToolResultParts = (): TraceMessagePart[] =>
        selectedToolResults.map((result) => ({
            type: "tool_result",
            content: result.result,
            raw: {
                name: result.name,
                result: result.result,
            },
        }));
    const resolvedRequestMessages: TraceMessage[] =
        selectedIsLlm && selectedRequestMessages.length > 0
            ? selectedRequestMessages
            : selectedIsLlm &&
                selectedPrompt !== undefined &&
                stringifyValue(selectedPrompt).trim() !== ""
              ? [
                    {
                        role: "prompt",
                        content: stringifyValue(selectedPrompt),
                    },
                ]
              : selectedIsEmbeddings &&
                  selectedEmbeddingInput !== undefined &&
                  stringifyValue(selectedEmbeddingInput).trim() !== ""
                ? [
                      {
                          role: "embedding input",
                          content: stringifyValue(selectedEmbeddingInput),
                      },
                  ]
                : !selectedIsLlm && selectedHasTools && selectedToolCalls.length > 0
                  ? [
                        {
                            role: "assistant",
                            content: "Tool calls",
                            parts: buildToolCallParts(),
                        },
                    ]
                  : [];
    const resolvedResponseMessages: TraceMessage[] =
        selectedIsLlm && selectedResponseMessages.length > 0
            ? selectedResponseMessages
            : selectedIsLlm &&
                selectedResponseText !== undefined &&
                selectedResponseText.trim() !== ""
              ? [
                    {
                        role: "assistant",
                        content: selectedResponseText,
                    },
                ]
              : selectedToolCalls.length > 0
                ? [
                      {
                          role: "assistant",
                          content: "Tool calls",
                          parts: buildToolCallParts(),
                      },
                  ]
                : selectedToolResults.length > 0
                  ? [
                        {
                            role: "tool",
                            content: "Tool results",
                            parts: buildToolResultParts(),
                        },
                    ]
                  : [];

    const hasSelectedSpan = selectedDisplaySpan !== undefined;
    const hasSummaryContent =
        selectedIsLlm || selectedIsEmbeddings || selectedHasTools || selectedHasUrlGuardrails;
    const isToolSpanSummary =
        selectedHasTools && !selectedIsLlm && !selectedIsEmbeddings;
    const resolvedUrlGuardrailMessages: TraceMessage[] =
        selectedUrlGuardrailsMessage === undefined ? [] : [selectedUrlGuardrailsMessage];

    const headerRows: { label: string; value: string }[] = [];
    if (hasSelectedSpan) {
        headerRows.push(
            {
                label: "Span",
                value: selectedSpanLabel ?? "-",
            },
            {
                label: "Duration",
                value: selectedSpanDuration ?? "-",
            },
            {
                label: "Offset",
                value: formatOffsetMs(selectedOffsetMs),
            },
        );

        if (
            selectedTokenSummary !== undefined &&
            selectedTokenSummary.trim() !== ""
        ) {
            headerRows.push({
                label: "Tokens",
                value: selectedTokenSummary,
            });
        }
    }

    return {
        timingRows,
        selection: hasSelectedSpan
            ? {
                  headerRows,
                  systemInstructions: selectedSystemInstructions,
                  requestLabel: isToolSpanSummary ? undefined : "Request",
                  responseLabel: isToolSpanSummary ? undefined : "Response",
                  requestMessages: resolvedRequestMessages,
                  responseMessages:
                      resolvedUrlGuardrailMessages.length > 0
                          ? resolvedUrlGuardrailMessages
                          : resolvedResponseMessages,
                  hasSummaryContent,
                  showToolName: selectedIsLlm || isToolSpanSummary,
                  isEmbeddings: selectedIsEmbeddings,
              }
            : undefined,
    };
};
