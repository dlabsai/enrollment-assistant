import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import { Toggle } from "@va/shared/components/ui/toggle";
import { Fragment, type JSX, useEffect, useMemo, useRef, useState } from "react";

import {
    formatEstimatedUsdCost,
    formatLocaleNumber,
} from "../../lib/number-format";
import {
    getReadableProjectedDataEntries,
    type ProjectedDataValueType,
    sortProjectedOverviewItemsForDisplay,
} from "../lib/trace-projection-utils";
import {
    formatDurationMs,
    isRecord,
    parseJsonRecursively,
    type TraceMessage,
    type TraceMessagePart,
} from "../lib/trace-utils";
import type { TraceOverviewItem, TraceSpan } from "../types";
import { ContentValue } from "./trace-turn-content";
import {
    renderMarkdownValue,
    renderPlainTextValue,
    renderStructuredValue,
    stringifyFieldValue,
    stringifyValue,
} from "./trace-turn-content-utils";
import {
    buildMessageKey,
    buildMessagePartKey,
    getStringField,
} from "./trace-turn-message-utils";
import { formatOffsetMs } from "./trace-turn-metrics-utils";
import { buildSpanOverviewModel } from "./trace-turn-summary-model";

interface TraceTurnSummaryProps {
    overview: TraceOverviewItem[];
    selectedSpanId?: string;
    spans: TraceSpan[];
    traceStart: number | undefined;
    traceEnd: number | undefined;
}

interface ProjectedDetailRow {
    key: string;
    label: string;
    value: unknown;
    valueType: ProjectedDataValueType | "auto";
    markdownValue?: string;
}

const isJsonLikeProjectedString = (value: string): boolean => {
    const trimmed = value.trim();
    return trimmed.startsWith("{") || trimmed.startsWith("[");
};

const isStructuredProjectedValue = (value: unknown): boolean =>
    Array.isArray(value) ||
    isRecord(value) ||
    (typeof value === "string" && isJsonLikeProjectedString(value));

const getNumberValue = (value: unknown): number | undefined =>
    typeof value === "number" && Number.isFinite(value) ? value : undefined;

const getNumberField = (
    value: unknown,
    key: string,
): number | undefined => {
    if (!isRecord(value)) {
        return undefined;
    }
    return getNumberValue(value[key]);
};

const formatTokenWithCost = (
    tokens: string | number,
    cost: number | undefined,
): string => {
    const tokenText =
        typeof tokens === "number" ? formatLocaleNumber(tokens) : tokens;
    return cost === undefined
        ? tokenText
        : `${tokenText} · ${formatEstimatedUsdCost(cost)}`;
};

const renderProjectedScalarValue = (key: string, value: unknown): JSX.Element => (
    <div className="text-muted-foreground text-xs break-words whitespace-pre-wrap">
        {stringifyFieldValue(key, value)}
    </div>
);

const renderProjectedValue = (key: string, value: unknown, formatted: boolean): JSX.Element => {
    if (isStructuredProjectedValue(value)) {
        return (
            <ContentValue
                formatted={formatted}
                value={value}
            />
        );
    }
    return renderProjectedScalarValue(key, value);
};

const renderProjectedMarkdownCard = (
    value: string,
    formatted: boolean,
): JSX.Element => (
    <div className="border-muted min-w-0 rounded-md border px-3 py-2 text-sm">
        {formatted ? renderMarkdownValue(value) : renderPlainTextValue(value)}
    </div>
);

const renderProjectedDetailValue = (
    row: ProjectedDetailRow,
    formatted: boolean,
): JSX.Element => {
    if (row.valueType === "markdown") {
        if (formatted) {
            const markdownValue =
                row.markdownValue ??
                (typeof row.value === "string" ? row.value : undefined);
            if (markdownValue !== undefined) {
                return renderProjectedMarkdownCard(markdownValue, true);
            }
        }
        if (typeof row.value === "string") {
            return renderProjectedMarkdownCard(row.value, false);
        }
        return renderProjectedValue(row.key, row.value, false);
    }
    if (row.valueType === "scalar") {
        return renderProjectedScalarValue(row.key, row.value);
    }
    return renderProjectedValue(row.key, row.value, formatted);
};

const ProjectedDetailsGrid = ({
    formatted,
    rows,
}: {
    formatted: boolean;
    rows: ProjectedDetailRow[];
}): JSX.Element => (
    <div className="grid grid-cols-[140px_minmax(0,1fr)] items-start gap-x-3 gap-y-0 text-sm leading-tight">
        {rows.map((row) => (
            <Fragment key={row.key}>
                <div className="text-xs font-semibold">{row.label}</div>
                <div className="min-w-0">
                    {renderProjectedDetailValue(row, formatted)}
                </div>
            </Fragment>
        ))}
    </div>
);

interface BackendOverviewRow {
    item: TraceOverviewItem;
    offsetPct: number;
    widthPct: number;
    start: number;
    depth: number;
    value: string;
    barClass: string;
}

const overviewStartMs = (item: TraceOverviewItem): number | undefined => {
    if (item.start_time === null) {
        return undefined;
    }
    const value = Date.parse(item.start_time);
    return Number.isNaN(value) ? undefined : value;
};

const formatOverviewDuration = (durationMs: number | null): string => formatDurationMs(durationMs);

const getStandardModelValue = (item: TraceOverviewItem): string | undefined => {
    if (item.type !== "agent" && item.type !== "llm") {
        return undefined;
    }
    const {model} = item.data;
    return typeof model === "string" && model.trim() !== ""
        ? model
        : undefined;
};

const overviewBarClass = (item: TraceOverviewItem): string => {
    switch (item.type) {
        case "agent":
        case "llm": {
            return "bg-chart-1";
        }
        case "tool": {
            return "bg-chart-2";
        }
        case "retrieval":
        case "embedding": {
            return "bg-chart-3";
        }
        case "url_guardrails": {
            return "bg-chart-4";
        }
        case "conversation_turn": {
            return "bg-chart-5";
        }
        case "evaluation": {
            return "bg-chart-5";
        }
        case "evaluation_case": {
            return "bg-chart-2";
        }
        case "evaluation_result": {
            const scoreLabel = item.data.score_label;
            if (scoreLabel === "fail") {
                return "bg-destructive";
            }
            if (scoreLabel === "pass") {
                return "bg-chart-3";
            }
            return "bg-chart-4";
        }
        case "other": {
            return "bg-muted-foreground";
        }
        default: {
            return "bg-muted-foreground";
        }
    }
};

const buildOverviewDepth = (
    item: TraceOverviewItem,
    itemBySpanId: Map<string, TraceOverviewItem>,
): number => {
    let depth = 0;
    let parentId = item.parent_span_id;
    const seen = new Set<string>();
    while (typeof parentId === "string" && parentId.trim() !== "") {
        if (seen.has(parentId)) {
            return depth;
        }
        seen.add(parentId);
        const parent = itemBySpanId.get(parentId);
        if (parent === undefined) {
            return depth;
        }
        depth += 1;
        parentId = parent.parent_span_id;
    }
    return depth;
};

const buildBackendOverviewRows = ({
    overview,
    traceEnd,
    traceStart,
}: {
    overview: TraceOverviewItem[];
    traceStart: number | undefined;
    traceEnd: number | undefined;
}): BackendOverviewRow[] => {
    const rangeDuration =
        traceStart !== undefined && traceEnd !== undefined
            ? Math.max(traceEnd - traceStart, 1)
            : undefined;
    const orderedOverview = sortProjectedOverviewItemsForDisplay(overview);
    const itemBySpanId = new Map(overview.map((item) => [item.span_id, item]));
    return orderedOverview
        .map((item) => {
            const start = overviewStartMs(item) ?? traceStart ?? 0;
            const duration = item.duration_ms ?? 0;
            const offsetPct =
                rangeDuration === undefined || traceStart === undefined
                    ? 0
                    : Math.max(
                          0,
                          Math.min(
                              100,
                              ((start - traceStart) / rangeDuration) * 100,
                          ),
                      );
            const widthPct =
                rangeDuration === undefined
                    ? 100
                    : Math.max(0.5, Math.min(100, (duration / rangeDuration) * 100));
            return {
                item,
                offsetPct,
                widthPct,
                start,
                depth: buildOverviewDepth(item, itemBySpanId),
                value: formatOverviewDuration(item.duration_ms),
                barClass: overviewBarClass(item),
            };
        });
};

const resolveToolName = (raw: Record<string, unknown> | undefined): string => {
    if (!raw) {
        return "tool";
    }
    const functionData = isRecord(raw.function) ? raw.function : undefined;
    return (
        getStringField(raw, "name") ??
        getStringField(raw, "tool_name") ??
        getStringField(raw, "tool") ??
        (functionData ? getStringField(functionData, "name") : undefined) ??
        "tool"
    );
};

const renderToolCallPart = (part: TraceMessagePart): JSX.Element => {
    const raw = isRecord(part.raw) ? part.raw : undefined;
    const name = resolveToolName(raw);
    const functionData =
        raw && isRecord(raw.function) ? raw.function : undefined;
    const argumentsValue =
        raw === undefined
            ? {}
            : (raw.arguments ??
              (functionData ? functionData.arguments : undefined) ??
              raw.args ??
              raw.input ??
              {});
    const parsedArguments = parseJsonRecursively(argumentsValue);

    return (
        <div className="space-y-2">
            <div className="text-xs font-semibold uppercase">Tool call</div>
            <div className="text-sm font-semibold">{name}</div>
            {renderStructuredValue(parsedArguments)}
        </div>
    );
};

const renderToolResultPart = (part: TraceMessagePart): JSX.Element => {
    const raw = isRecord(part.raw) ? part.raw : undefined;
    const name = resolveToolName(raw);
    const resultValue =
        raw === undefined
            ? (part.content ?? "-")
            : (raw.result ??
              raw.output ??
              raw.response ??
              raw.content ??
              raw.value ??
              raw.data ??
              part.content ??
              "-");
    const parsedResult = parseJsonRecursively(resultValue);

    return (
        <div className="space-y-2">
            <div className="text-xs font-semibold uppercase">Tool result</div>
            <div className="text-sm font-semibold">{name}</div>
            {renderStructuredValue(parsedResult)}
        </div>
    );
};

const parseToolValue = (value: unknown): unknown => parseJsonRecursively(value);

const renderToolKeyValue = (value: unknown): JSX.Element => {
    const parsed = parseToolValue(value);
    if (!isRecord(parsed)) {
        return (
            <div className="text-muted-foreground text-xs whitespace-pre-wrap">
                {stringifyValue(parsed)}
            </div>
        );
    }

    return (
        <div className="grid grid-cols-[160px_1fr] gap-x-3 gap-y-2 text-xs">
            {Object.entries(parsed).map(([key, entry]) => (
                <div
                    className="contents"
                    key={key}
                >
                    <div className="font-semibold break-words">{key}</div>
                    <div className="text-muted-foreground break-words whitespace-pre-wrap">
                        {stringifyFieldValue(key, entry)}
                    </div>
                </div>
            ))}
        </div>
    );
};

const renderSummaryToolArguments = (value: unknown): JSX.Element => (
    <div className="bg-muted/30 rounded-md border p-3">{renderToolKeyValue(value)}</div>
);

const renderSummaryToolResultValue = (
    value: unknown,
    formatted: boolean,
): JSX.Element => (
    <ContentValue
        formatted={formatted}
        value={value}
    />
);

const renderSummaryToolCallPart = (
    part: TraceMessagePart,
    showToolName: boolean,
): JSX.Element => {
    const raw = isRecord(part.raw) ? part.raw : undefined;
    const name = resolveToolName(raw);
    const functionData =
        raw && isRecord(raw.function) ? raw.function : undefined;
    const argumentsValue =
        raw === undefined
            ? {}
            : (raw.arguments ??
              (functionData ? functionData.arguments : undefined) ??
              raw.args ??
              raw.input ??
              {});

    return showToolName ? (
        <div className="space-y-1">
            <div className="text-xs font-semibold">{name}</div>
            {renderSummaryToolArguments(argumentsValue)}
        </div>
    ) : (
        renderSummaryToolArguments(argumentsValue)
    );
};

const renderSummaryToolResultPart = (
    part: TraceMessagePart,
    showToolName: boolean,
    formatted: boolean,
): JSX.Element => {
    const raw = isRecord(part.raw) ? part.raw : undefined;
    const name = resolveToolName(raw);
    const resultValue =
        raw === undefined
            ? (part.content ?? "-")
            : (raw.result ??
              raw.output ??
              raw.response ??
              raw.content ??
              raw.value ??
              raw.data ??
              part.content ??
              "-");

    return showToolName ? (
        <div className="space-y-1">
            <div className="text-xs font-semibold">{name}</div>
            {renderSummaryToolResultValue(resultValue, formatted)}
        </div>
    ) : (
        renderSummaryToolResultValue(resultValue, formatted)
    );
};

const renderSummaryToolMessage = (
    message: TraceMessage,
    formatted: boolean,
): JSX.Element => renderSummaryToolResultValue(message.content, formatted);

const renderSummaryMessageContent = (
    message: TraceMessage,
    formatted: boolean,
    showToolName: boolean,
): JSX.Element => {
    const parts = message.parts ?? [];
    if (parts.length === 0) {
        if (message.role === "tool") {
            return formatted
                ? renderSummaryToolMessage(message, formatted)
                : renderStructuredValue(parseJsonRecursively(message.content));
        }
        return formatted
            ? renderMarkdownValue(message.content)
            : renderPlainTextValue(message.content);
    }

    return (
        <div className="space-y-2">
            {parts.map((part) =>
                formatted ? (
                    <div
                        className="space-y-1"
                        key={buildMessagePartKey(part)}
                    >
                        {part.type === "tool_call" ? (
                            showToolName ? (
                                <>
                                    <div className="text-muted-foreground text-xs uppercase">
                                        {part.type}
                                    </div>
                                    {renderSummaryToolCallPart(part, true)}
                                </>
                            ) : (
                                renderSummaryToolCallPart(part, false)
                            )
                        ) : part.type === "tool_result" ||
                          part.type === "tool_call_response" ? (
                            showToolName ? (
                                <>
                                    <div className="text-muted-foreground text-xs uppercase">
                                        {part.type}
                                    </div>
                                    {renderSummaryToolResultPart(part, true, formatted)}
                                </>
                            ) : (
                                renderSummaryToolResultPart(part, false, formatted)
                            )
                        ) : (
                            <>
                                <div className="text-muted-foreground text-xs uppercase">
                                    {part.type}
                                </div>
                                {renderMarkdownValue(part.content ?? part.raw)}
                            </>
                        )}
                    </div>
                ) : (
                    <div
                        className="space-y-1"
                        key={buildMessagePartKey(part)}
                    >
                        <div className="text-muted-foreground text-xs uppercase">
                            {part.type}
                        </div>
                        {part.type === "tool_call"
                            ? renderToolCallPart(part)
                            : part.type === "tool_result" ||
                                part.type === "tool_call_response"
                              ? renderToolResultPart(part)
                              : renderPlainTextValue(part.content ?? part.raw)}
                    </div>
                ),
            )}
        </div>
    );
};

export const TraceTurnSummary = ({
    overview,
    selectedSpanId,
    spans,
    traceStart,
    traceEnd,
}: TraceTurnSummaryProps): JSX.Element => {
    const [summaryFormatted, setSummaryFormatted] = useState(true);
    const [selectedTimingSpanId, setSelectedTimingSpanId] = useState(selectedSpanId);
    const resolvedSelectedTimingSpanId = selectedTimingSpanId ?? selectedSpanId;
    const timelineScrollRef = useRef<HTMLDivElement | null>(null);

    const backendOverviewRows = useMemo(
        () => buildBackendOverviewRows({ overview, traceEnd, traceStart }),
        [overview, traceEnd, traceStart],
    );
    const selectedBackendOverviewRow =
        resolvedSelectedTimingSpanId === undefined
            ? undefined
            : backendOverviewRows.find(
                  (entry) => entry.item.span_id === resolvedSelectedTimingSpanId,
              );
    const useBackendOverview = backendOverviewRows.length > 0;

    useEffect(() => {
        if (selectedSpanId === undefined) {
            return;
        }
        const container = timelineScrollRef.current;
        if (container === null) {
            return;
        }
        const element = container.querySelector(
            `[data-overview-span-id="${selectedSpanId}"]`,
        );
        if (element instanceof HTMLElement) {
            element.scrollIntoView({ block: "center" });
        }
    }, [selectedSpanId, useBackendOverview]);

    const overviewModel = useMemo(
        () =>
            buildSpanOverviewModel({
                spans,
                traceStart,
                traceEnd,
                selectedSpanId: resolvedSelectedTimingSpanId,
            }),
        [resolvedSelectedTimingSpanId, spans, traceEnd, traceStart],
    );
    const { timingRows } = overviewModel;
    const { selection } = overviewModel;
    const hasSelectedSpan = selection !== undefined;
    const systemInstructions = selection?.systemInstructions;
    const requestMessages = selection?.requestMessages ?? [];
    const responseMessages = selection?.responseMessages ?? [];
    const hasSummaryContent = selection?.hasSummaryContent ?? false;
    const requestLabel = selection?.requestLabel;
    const responseLabel = selection?.responseLabel;
    const showToolName = selection?.showToolName ?? false;
    const isEmbeddings = selection?.isEmbeddings ?? false;
    const headerRows = selection?.headerRows ?? [];

    const renderMessageList = (
        messages: TraceMessage[],
        includeToolNames: boolean,
    ): JSX.Element => (
        <div className="space-y-3">
            {messages.map((message) => {
                const parts = message.parts ?? [];
                const isToolOnlyMessage =
                    message.role === "tool" ||
                    (parts.length > 0 &&
                        parts.every(
                            (part) =>
                                part.type === "tool_call" ||
                                part.type === "tool_result" ||
                                part.type === "tool_call_response",
                        ));
                return (
                    <div
                        className="border-muted space-y-1 border-l pl-3"
                        key={`summary-message-${buildMessageKey(message)}`}
                    >
                        {isToolOnlyMessage ? undefined : (
                            <div className="text-muted-foreground text-xs uppercase">
                                {message.role}
                            </div>
                        )}
                        {renderSummaryMessageContent(
                            message,
                            summaryFormatted,
                            includeToolNames,
                        )}
                    </div>
                );
            })}
        </div>
    );

    const timingList = useBackendOverview ? (
        <div className="text-xs">
            {backendOverviewRows.map((entry) => {
                const spanId = entry.item.span_id;
                const isSelected = spanId === resolvedSelectedTimingSpanId;
                return (
                    <button
                        className={`hover:border-primary/50 hover:bg-primary/10 grid w-full grid-cols-[minmax(220px,1fr)_70px_minmax(160px,1.2fr)] items-center gap-x-3 rounded-none border border-transparent px-1 py-0.5 text-left transition-none ${
                            isSelected
                                ? "border-primary bg-primary/15 ring-primary/30 shadow-sm ring-1"
                                : ""
                        }`}
                        data-overview-span-id={spanId}
                        key={spanId}
                        onClick={() => {
                            setSelectedTimingSpanId(spanId);
                        }}
                        type="button"
                    >
                        <div
                            className="font-semibold"
                            style={{
                                paddingLeft: `${entry.depth * 16}px`,
                            }}
                        >
                            {entry.item.title}
                        </div>
                        <div className="text-muted-foreground tabular-nums">
                            {entry.value}
                        </div>
                        <div className="bg-muted relative h-2 overflow-hidden rounded">
                            <div
                                className={`absolute inset-y-0 rounded ${entry.barClass}`}
                                style={{
                                    left: `${entry.offsetPct}%`,
                                    width: `${entry.widthPct}%`,
                                }}
                            />
                        </div>
                    </button>
                );
            })}
        </div>
    ) : (
        <div className="text-xs">
            {timingRows.map((entry) => {
                const isSelected = entry.spanId === resolvedSelectedTimingSpanId;
                return (
                    <button
                        className={`hover:border-primary/50 hover:bg-primary/10 grid w-full grid-cols-[minmax(220px,1fr)_70px_minmax(160px,1.2fr)] items-center gap-x-3 rounded-none border border-transparent px-1 py-0.5 text-left transition-none ${
                            isSelected
                                ? "border-primary bg-primary/15 ring-primary/30 shadow-sm ring-1"
                                : ""
                        }`}
                        data-overview-span-id={entry.spanId}
                        key={entry.spanId}
                        onClick={() => {
                            setSelectedTimingSpanId(entry.spanId);
                        }}
                        type="button"
                    >
                        <div
                            className="font-semibold"
                            style={{
                                paddingLeft: `${entry.depth * 16}px`,
                            }}
                        >
                            {entry.label}
                        </div>
                        <div className="text-muted-foreground tabular-nums">
                            {entry.value}
                        </div>
                        <div className="bg-muted relative h-2 overflow-hidden rounded">
                            <div
                                className={`absolute inset-y-0 rounded ${entry.barClass}`}
                                style={{
                                    left: `${entry.offsetPct}%`,
                                    width: `${entry.widthPct}%`,
                                }}
                            />
                        </div>
                    </button>
                );
            })}
        </div>
    );

    const selectedBackendOutputText =
        typeof selectedBackendOverviewRow?.item.data.output_text === "string" &&
        selectedBackendOverviewRow.item.data.output_text.trim() !== ""
            ? selectedBackendOverviewRow.item.data.output_text
            : undefined;
    const selectedBackendInputText =
        typeof selectedBackendOverviewRow?.item.data.input_text === "string" &&
        selectedBackendOverviewRow.item.data.input_text.trim() !== ""
            ? selectedBackendOverviewRow.item.data.input_text
            : undefined;
    const selectedBackendDataEntries =
        selectedBackendOverviewRow === undefined
            ? []
            : getReadableProjectedDataEntries(selectedBackendOverviewRow.item);
    const selectedBackendModel =
        selectedBackendOverviewRow === undefined
            ? undefined
            : getStandardModelValue(selectedBackendOverviewRow.item);
    const selectedBackendReasoningEffort =
        typeof selectedBackendOverviewRow?.item.data.reasoning_effort === "string" &&
        selectedBackendOverviewRow.item.data.reasoning_effort.trim() !== ""
            ? selectedBackendOverviewRow.item.data.reasoning_effort
            : undefined;
    const selectedBackendUncachedInputTokens =
        selectedBackendOverviewRow?.item.data.uncached_input_tokens;
    const selectedBackendCacheReadTokens =
        selectedBackendOverviewRow?.item.data.cache_read_input_tokens;
    const selectedBackendOutputTokens =
        selectedBackendOverviewRow?.item.data.output_tokens;
    const selectedBackendCostBreakdown =
        selectedBackendOverviewRow?.item.data.cost_breakdown;
    const selectedBackendTokenRows = [
        [
            "Uncached input",
            selectedBackendUncachedInputTokens,
            getNumberField(selectedBackendCostBreakdown, "input_cost"),
        ],
        [
            "Cached input",
            selectedBackendCacheReadTokens,
            getNumberField(selectedBackendCostBreakdown, "cache_read_input_cost"),
        ],
        [
            "Output",
            selectedBackendOutputTokens,
            getNumberField(selectedBackendCostBreakdown, "output_cost"),
        ],
    ]
        .filter(
            (entry): entry is [string, string | number, number | undefined] =>
                typeof entry[1] === "string" || typeof entry[1] === "number",
        )
        .map(([label, value, cost]) => [
            label,
            formatTokenWithCost(value, cost),
        ] as const);

    const renderSummarySection = (
        label: string | undefined,
        messages: TraceMessage[],
        emptyLabel: string,
    ): JSX.Element => (
        <section className="space-y-2">
            {label !== undefined && label.trim() !== "" ? (
                <h3 className="text-xs font-semibold uppercase">{label}</h3>
            ) : undefined}
            {messages.length > 0 ? (
                renderMessageList(messages, showToolName)
            ) : (
                <div className="text-muted-foreground text-xs">
                    {emptyLabel}
                </div>
            )}
        </section>
    );

    const selectedBackendHeaderRows: { label: string; value: string | number }[] =
        selectedBackendOverviewRow === undefined
            ? []
            : [
                  { label: "Step", value: selectedBackendOverviewRow.item.title },
                  ...(selectedBackendModel === undefined
                      ? []
                      : [{ label: "Model", value: selectedBackendModel }]),
                  ...(selectedBackendReasoningEffort === undefined
                      ? []
                      : [
                            {
                                label: "Reasoning effort",
                                value: selectedBackendReasoningEffort,
                            },
                        ]),
                  { label: "Duration", value: selectedBackendOverviewRow.value },
                  {
                      label: "Offset",
                      value: formatOffsetMs(
                          traceStart === undefined
                              ? undefined
                              : selectedBackendOverviewRow.start - traceStart,
                      ),
                  },
                  ...selectedBackendTokenRows.map(([label, value]) => ({
                      label,
                      value,
                  })),
                  ...(selectedBackendOverviewRow.item.status_code !== null &&
                  !["OK", "UNSET"].includes(
                      selectedBackendOverviewRow.item.status_code,
                  )
                      ? [
                            {
                                label: "Status",
                                value: selectedBackendOverviewRow.item.status_code,
                            },
                        ]
                      : []),
              ];

    const selectedBackendDetailRows: ProjectedDetailRow[] =
        selectedBackendOverviewRow === undefined
            ? []
            : [
                  ...selectedBackendHeaderRows.map((entry) => ({
                      key: `header-${entry.label}`,
                      label: entry.label,
                      value: entry.value,
                      valueType: "scalar" as const,
                  })),
                  ...(selectedBackendInputText === undefined
                      ? []
                      : [
                            {
                                key: "input",
                                label: "Input",
                                value: selectedBackendInputText,
                                valueType: "markdown" as const,
                            },
                        ]),
                  ...(selectedBackendOutputText === undefined
                      ? []
                      : [
                            {
                                key: "response",
                                label: "Response",
                                value: selectedBackendOutputText,
                                valueType: "markdown" as const,
                            },
                        ]),
                  ...selectedBackendDataEntries.map((entry) => ({
                      key: entry.key,
                      label: entry.label,
                      value: entry.value,
                      valueType:
                          entry.valueType ??
                          (entry.key === "guardrails_feedback" ||
                          entry.key === "explanation" ||
                          entry.key === "system_instructions"
                              ? ("markdown" as const)
                              : ("auto" as const)),
                      markdownValue: entry.markdownValue,
                  })),
              ];

    const backendSummaryDetails =
        selectedBackendOverviewRow === undefined ? (
            <div className="text-muted-foreground text-xs">
                Select a trace step to view projected details.
            </div>
        ) : (
            <ProjectedDetailsGrid
                formatted={summaryFormatted}
                rows={selectedBackendDetailRows}
            />
        );

    const legacySummaryDetails = (
        <div className="space-y-4">
            {hasSelectedSpan ? (
                <div className="space-y-1 text-xs">
                    {headerRows.map((entry) => (
                        <div
                            className="grid grid-cols-[140px_1fr] items-center gap-x-3"
                            key={`selected-${entry.label}`}
                        >
                            <div className="font-semibold">{entry.label}</div>
                            <div className="text-muted-foreground">
                                {entry.value}
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-muted-foreground text-xs">
                    Select a span to view request/response details.
                </div>
            )}
            {hasSelectedSpan ? (
                hasSummaryContent ? (
                    <div className="space-y-4 text-sm">
                        {systemInstructions !== undefined &&
                        systemInstructions.trim() !== ""
                            ? renderSummarySection(
                                  "System Instructions",
                                  [
                                      {
                                          role: "system",
                                          content: systemInstructions,
                                      },
                                  ],
                                  "No system instructions for this span.",
                              )
                            : undefined}
                        {renderSummarySection(
                            requestLabel,
                            requestMessages,
                            "No request content for this span.",
                        )}
                        {isEmbeddings && responseMessages.length === 0
                            ? undefined
                            : renderSummarySection(
                                  responseLabel,
                                  responseMessages,
                                  "No response content for this span.",
                              )}
                    </div>
                ) : (
                    <div className="text-muted-foreground text-xs">
                        Select a span with request/response details.
                    </div>
                )
            ) : undefined}
        </div>
    );

    const summaryDetails = useBackendOverview
        ? backendSummaryDetails
        : legacySummaryDetails;

    return (
        <ResizablePanelGroup
            className="h-full min-h-0 min-w-0"
            id="trace-turn-summary-layout"
            orientation="horizontal"
        >
            <ResizablePanel
                className="min-h-0 min-w-0"
                defaultSize="45%"
                id="trace-turn-summary-timeline-panel"
                minSize="38%"
            >
                <div
                    className="h-full min-h-0 min-w-0 overflow-auto"
                    ref={timelineScrollRef}
                >
                    <div className="space-y-3 px-4 py-4">
                        <div className="text-muted-foreground text-xs uppercase">
                            Timeline
                        </div>
                        {timingList}
                    </div>
                </div>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel
                className="min-h-0 min-w-0"
                defaultSize="55%"
                id="trace-turn-summary-details-panel"
                minSize="40%"
            >
                <div className="h-full min-h-0 min-w-0 overflow-auto">
                    <div className="px-4 py-4">
                        <div className="mb-2 flex items-center justify-end gap-3">
                            <Toggle
                                onPressedChange={setSummaryFormatted}
                                pressed={summaryFormatted}
                                size="sm"
                                variant="outline"
                            >
                                {summaryFormatted ? "Formatted" : "Plain"}
                            </Toggle>
                        </div>
                        {summaryDetails}
                    </div>
                </div>
            </ResizablePanel>
        </ResizablePanelGroup>
    );
};
