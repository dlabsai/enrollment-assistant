import { Toggle } from "@va/shared/components/ui/toggle";
import { Fragment, type JSX, useMemo, useState } from "react";

import {
    formatLocaleNumber,
    formatUsdCost,
} from "../../lib/number-format";
import type { TraceCollapseControls } from "../hooks/use-trace-collapse";
import type { TraceLayoutScope } from "../lib/trace-layout";
import { getAggregateFailedResultCount } from "../lib/trace-outcomes";
import {
    getReadableProjectedDataEntries,
    type ProjectedDataValueType,
    sortProjectedOverviewItemsForDisplay,
} from "../lib/trace-projection-utils";
import { buildVisibleTraceTimelineRows } from "../lib/trace-timeline";
import {
    formatDurationMs,
    isRecord,
    parseJsonRecursively,
    type TraceMessage,
    type TraceMessagePart,
} from "../lib/trace-utils";
import type { TraceOverviewItem, TraceSpan } from "../types";
import { TraceCollapseAllButton } from "./trace-collapse-all-button";
import { TraceOutcomeBadge } from "./trace-outcome-badge";
import { TraceSplitLayout } from "./trace-split-layout";
import { TraceTimeline, type TraceTimelineRow } from "./trace-timeline";
import {
    ContentValue,
    ExpandableMarkdownValue,
} from "./trace-turn-content";
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
    collapseControls: TraceCollapseControls;
    overview: TraceOverviewItem[];
    selectedSpanId?: string;
    onSelectSpan: (spanId: string) => void;
    layoutScope?: TraceLayoutScope;
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

const formatTokenUsage = (
    tokens: string | number,
    cost: number | undefined,
): string => {
    const tokenText =
        typeof tokens === "number" ? formatLocaleNumber(tokens) : tokens;
    return cost === undefined
        ? tokenText
        : `${tokenText} · ${formatUsdCost(cost)}`;
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
        <ExpandableMarkdownValue
            content={value}
            formatted={formatted}
        />
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
    offsetMs: number;
    durationMs: number;
    start: number;
    depth: number;
    value: string;
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
    traceStart,
}: {
    overview: TraceOverviewItem[];
    traceStart: number | undefined;
}): BackendOverviewRow[] => {
    const orderedOverview = sortProjectedOverviewItemsForDisplay(overview);
    const itemBySpanId = new Map(overview.map((item) => [item.span_id, item]));
    return orderedOverview.map((item) => {
        const start = overviewStartMs(item) ?? traceStart ?? 0;
        return {
            item,
            offsetMs:
                traceStart === undefined ? 0 : Math.max(start - traceStart, 0),
            durationMs: Math.max(item.duration_ms ?? 0, 0),
            start,
            depth: buildOverviewDepth(item, itemBySpanId),
            value: formatOverviewDuration(item.duration_ms),
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
    collapseControls,
    overview,
    selectedSpanId,
    onSelectSpan,
    layoutScope = "page",
    spans,
    traceStart,
    traceEnd,
}: TraceTurnSummaryProps): JSX.Element => {
    const [summaryFormatted, setSummaryFormatted] = useState(true);
    const { collapsedSpanIds, toggleSpan } = collapseControls;

    const backendOverviewRows = useMemo(
        () => buildBackendOverviewRows({ overview, traceStart }),
        [overview, traceStart],
    );
    const backendOverviewRowsBySpanId = useMemo(
        () =>
            new Map(
                backendOverviewRows.map((entry) => [
                    entry.item.span_id,
                    entry,
                ]),
            ),
        [backendOverviewRows],
    );
    const selectedBackendOverviewRow =
        selectedSpanId === undefined
            ? undefined
            : backendOverviewRowsBySpanId.get(selectedSpanId);
    const useBackendOverview = backendOverviewRows.length > 0;

    const overviewModel = useMemo(
        () =>
            useBackendOverview
                ? undefined
                : buildSpanOverviewModel({
                      spans,
                      traceStart,
                      traceEnd,
                      selectedSpanId,
                  }),
        [
            selectedSpanId,
            spans,
            traceEnd,
            traceStart,
            useBackendOverview,
        ],
    );
    const selection = overviewModel?.selection;
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

    const timelineRows = useMemo<TraceTimelineRow[]>(
        () =>
            useBackendOverview
                ? backendOverviewRows.map((entry) => ({
                      id: entry.item.span_id,
                      parentId: entry.item.parent_span_id,
                      label: entry.item.title,
                      depth: entry.depth,
                      durationLabel: entry.value,
                      offsetMs: entry.offsetMs,
                      durationMs: entry.durationMs,
                      outcome: entry.item.outcome,
                      failedResultCount: getAggregateFailedResultCount(
                          entry.item,
                      ),
                  }))
                : (overviewModel?.timingRows ?? []).map((entry) => ({
                      id: entry.spanId,
                      label: entry.label,
                      depth: entry.depth,
                      durationLabel: entry.value,
                      offsetMs: entry.offsetMs,
                      durationMs: entry.durationMs,
                  })),
        [backendOverviewRows, overviewModel, useBackendOverview],
    );
    const expandableSpanIds = useMemo(
        () =>
            new Set(
                buildVisibleTraceTimelineRows(timelineRows, new Set())
                    .filter((row) => row.hasChildren)
                    .map((row) => row.id),
            ),
        [timelineRows],
    );
    const traceDurationMs =
        traceStart === undefined || traceEnd === undefined
            ? undefined
            : Math.max(traceEnd - traceStart, 0);
    const timingList = (
        <TraceTimeline
            collapsedSpanIds={collapsedSpanIds}
            layoutScope={layoutScope}
            onSelectSpan={onSelectSpan}
            onToggleSpan={toggleSpan}
            rows={timelineRows}
            selectedSpanId={selectedSpanId}
            traceDurationMs={traceDurationMs}
        />
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
    const selectedBackendTotalCost = getNumberValue(
        selectedBackendOverviewRow?.item.data.total_cost,
    );
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
            formatTokenUsage(value, cost),
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
                  ...(selectedBackendTotalCost === undefined
                      ? []
                      : [
                            {
                                label: "Cost",
                                value: formatUsdCost(selectedBackendTotalCost),
                            },
                        ]),
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
            <div className="space-y-3">
                <TraceOutcomeBadge
                    failedResultCount={getAggregateFailedResultCount(
                        selectedBackendOverviewRow.item,
                    )}
                    outcome={selectedBackendOverviewRow.item.outcome}
                />
                <ProjectedDetailsGrid
                    formatted={summaryFormatted}
                    rows={selectedBackendDetailRows}
                />
            </div>
        );

    const fallbackSummaryDetails = (
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
        : fallbackSummaryDetails;

    return (
        <TraceSplitLayout
            detail={
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
            }
            navigation={
                <div className="flex h-full min-h-0 min-w-0 flex-col">
                    <div className="border-border flex items-center justify-end border-b px-3 py-2">
                        <TraceCollapseAllButton
                            collapseControls={collapseControls}
                            expandableSpanIds={expandableSpanIds}
                        />
                    </div>
                    <div className="min-h-0 flex-1">{timingList}</div>
                </div>
            }
            scope={layoutScope}
        />
    );
};
