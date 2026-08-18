import { useVirtualizer } from "@tanstack/react-virtual";
import { Toggle } from "@va/shared/components/ui/toggle";
import { ChevronDown, ChevronRight } from "lucide-react";
import { type JSX, useEffect, useMemo, useRef, useState } from "react";

import type { TraceCollapseControls } from "../hooks/use-trace-collapse";
import type { TraceLayoutScope } from "../lib/trace-layout";
import {
    getAggregateFailedResultCount,
    getTraceSpanOutcome,
    traceOutcomeRowClass,
} from "../lib/trace-outcomes";
import { buildSpanTree, getStringAttribute } from "../lib/trace-utils";
import {
    buildSpanHierarchy,
    formatSpanDuration,
    getSpanTimelineLayout,
    getTraceTimeRange,
    type SpanTreeNode,
} from "../lib/trace-view-utils";
import type { TraceOverviewItem, TraceSpan } from "../types";
import { TraceCollapseAllButton } from "./trace-collapse-all-button";
import { TraceOutcomeBadge } from "./trace-outcome-badge";
import { TraceTimeline, type TraceTimelineRow } from "./trace-timeline";

type SpanViewMode = "tree" | "timeline";
type OverviewBySpanId = ReadonlyMap<string, TraceOverviewItem>;

const TREE_ROW_ESTIMATE_PX = 78;
const TREE_ROW_OVERSCAN = 12;

interface VisibleSpanTreeNode {
    node: SpanTreeNode;
    depth: number;
}

const flattenExpandedSpanTree = (
    tree: SpanTreeNode[],
    expandedSpanIds: Set<string>,
): VisibleSpanTreeNode[] => {
    const visible: VisibleSpanTreeNode[] = [];
    const visit = (nodes: SpanTreeNode[], depth: number): void => {
        for (const node of nodes) {
            visible.push({ node, depth });
            if (
                node.children.length > 0 &&
                expandedSpanIds.has(node.span.span_id)
            ) {
                visit(node.children, depth + 1);
            }
        }
    };
    visit(tree, 0);
    return visible;
};

const SpanTimelineList = ({
    collapsedSpanIds,
    layoutScope,
    spans,
    selectedSpanId,
    onSelectSpan,
    onToggleSpan,
    overviewBySpanId,
}: {
    collapsedSpanIds: ReadonlySet<string>;
    layoutScope: TraceLayoutScope;
    spans: TraceSpan[];
    selectedSpanId: string | undefined;
    onSelectSpan: (spanId: string) => void;
    onToggleSpan: (spanId: string) => void;
    overviewBySpanId: OverviewBySpanId;
}): JSX.Element => {
    const flattened = useMemo(() => buildSpanTree(spans), [spans]);
    const { durationMs: traceDurationMs, end: traceEnd, start: traceStart } =
        useMemo(() => getTraceTimeRange(spans), [spans]);
    const rows = useMemo<TraceTimelineRow[]>(
        () =>
            flattened.map(({ span, depth }) => {
                const attributes = span.attributes ?? {};
                const agentName = getStringAttribute(
                    attributes,
                    "gen_ai.agent.name",
                );
                const model = getStringAttribute(
                    attributes,
                    "gen_ai.request.model",
                );
                const timelineLayout = getSpanTimelineLayout(
                    span,
                    traceStart,
                    traceEnd,
                );
                const overviewItem = overviewBySpanId.get(span.span_id);
                const outcome = getTraceSpanOutcome(span, overviewItem);

                return {
                    id: span.span_id,
                    parentId: span.parent_span_id,
                    label: span.name,
                    subtitle: [agentName, model]
                        .filter(
                            (item): item is string =>
                                typeof item === "string" &&
                                item.trim() !== "",
                        )
                        .join(" · "),
                    depth,
                    durationLabel: formatSpanDuration(span),
                    offsetMs: timelineLayout?.offsetMs ?? 0,
                    durationMs:
                        timelineLayout?.durationMs ?? span.duration_ms ?? 0,
                    outcome,
                    failedResultCount:
                        getAggregateFailedResultCount(overviewItem),
                };
            }),
        [flattened, overviewBySpanId, traceEnd, traceStart],
    );

    return (
        <TraceTimeline
            collapsedSpanIds={collapsedSpanIds}
            layoutScope={layoutScope}
            onSelectSpan={onSelectSpan}
            onToggleSpan={onToggleSpan}
            rows={rows}
            selectedSpanId={selectedSpanId}
            traceDurationMs={traceDurationMs}
        />
    );
};

const SpanTreeList = ({
    spans,
    selectedSpanId,
    expandedSpanIds,
    onSelectSpan,
    onToggleSpan,
    overviewBySpanId,
}: {
    spans: TraceSpan[];
    selectedSpanId: string | undefined;
    expandedSpanIds: Set<string>;
    onSelectSpan: (spanId: string) => void;
    onToggleSpan: (spanId: string) => void;
    overviewBySpanId: OverviewBySpanId;
}): JSX.Element => {
    const scrollRef = useRef<HTMLDivElement | null>(null);
    const tree = useMemo(() => buildSpanHierarchy(spans), [spans]);
    const visibleNodes = useMemo(
        () => flattenExpandedSpanTree(tree, expandedSpanIds),
        [expandedSpanIds, tree],
    );
    // eslint-disable-next-line react-hooks/incompatible-library
    const rowVirtualizer = useVirtualizer({
        count: visibleNodes.length,
        estimateSize: () => TREE_ROW_ESTIMATE_PX,
        getItemKey: (index) =>
            visibleNodes[index]?.node.span.span_id ?? index,
        getScrollElement: () => scrollRef.current,
        overscan: TREE_ROW_OVERSCAN,
        paddingEnd: 12,
        paddingStart: 12,
    });

    useEffect(() => {
        const selectedIndex = visibleNodes.findIndex(
            ({ node }) => node.span.span_id === selectedSpanId,
        );
        if (selectedIndex !== -1) {
            rowVirtualizer.scrollToIndex(selectedIndex, { align: "auto" });
        }
    }, [rowVirtualizer, selectedSpanId, visibleNodes]);

    return (
        <div
            className="h-full overflow-auto"
            ref={scrollRef}
        >
            <div
                className="relative w-full"
                style={{ height: `${rowVirtualizer.getTotalSize()}px` }}
            >
                {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                    const entry = visibleNodes[virtualRow.index];
                    if (entry === undefined) {
                        return null;
                    }
                    const { node, depth } = entry;
                    const { span, children } = node;
                    const attributes = span.attributes ?? {};
                    const agentName = getStringAttribute(
                        attributes,
                        "gen_ai.agent.name",
                    );
                    const model = getStringAttribute(
                        attributes,
                        "gen_ai.request.model",
                    );
                    const labelParts = [agentName, model].filter(
                        (item): item is string =>
                            typeof item === "string" &&
                            item.trim() !== "",
                    );
                    const hasChildren = children.length > 0;
                    const isExpanded = expandedSpanIds.has(span.span_id);
                    const overviewItem = overviewBySpanId.get(span.span_id);
                    const outcome = getTraceSpanOutcome(span, overviewItem);

                    return (
                        <div
                            className="absolute top-0 left-0 w-full px-4 py-1"
                            data-index={virtualRow.index}
                            key={span.span_id}
                            ref={rowVirtualizer.measureElement}
                            style={{
                                transform: `translateY(${virtualRow.start}px)`,
                            }}
                        >
                            <div
                                className={`hover:border-primary/50 hover:bg-primary/10 data-[selected=true]:border-primary data-[selected=true]:bg-primary/15 data-[selected=true]:ring-primary/30 flex w-full flex-col gap-2 rounded-none border border-transparent px-2 py-2 text-left transition-none data-[selected=true]:shadow-sm data-[selected=true]:ring-1 ${traceOutcomeRowClass(outcome)}`}
                                data-selected={
                                    selectedSpanId === span.span_id
                                }
                                onClick={() => {
                                    onSelectSpan(span.span_id);
                                }}
                                onKeyDown={(event) => {
                                    if (
                                        event.key === "Enter" ||
                                        event.key === " "
                                    ) {
                                        event.preventDefault();
                                        onSelectSpan(span.span_id);
                                    }
                                }}
                                role="button"
                                tabIndex={0}
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <div
                                        className="flex min-w-0 flex-1 items-start gap-2"
                                        style={{
                                            paddingLeft: `${depth * 16}px`,
                                        }}
                                    >
                                        {hasChildren ? (
                                            <button
                                                aria-label={
                                                    isExpanded
                                                        ? "Collapse span"
                                                        : "Expand span"
                                                }
                                                className="text-muted-foreground hover:text-foreground flex size-4 items-center justify-center"
                                                onClick={(event) => {
                                                    event.stopPropagation();
                                                    onToggleSpan(span.span_id);
                                                }}
                                                type="button"
                                            >
                                                {isExpanded ? (
                                                    <ChevronDown className="size-3.5" />
                                                ) : (
                                                    <ChevronRight className="size-3.5" />
                                                )}
                                            </button>
                                        ) : (
                                            <span className="inline-block size-4" />
                                        )}
                                        <div className="min-w-0 flex-1">
                                            <div className="text-sm font-medium break-words">
                                                {span.name}
                                            </div>
                                            <div className="text-muted-foreground text-xs break-words">
                                                {labelParts.join(" · ")}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="text-muted-foreground text-xs tabular-nums">
                                        {formatSpanDuration(span)}
                                    </div>
                                </div>
                                <TraceOutcomeBadge
                                    failedResultCount={getAggregateFailedResultCount(
                                        overviewItem,
                                    )}
                                    outcome={outcome}
                                />
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export const SpanNavigator = ({
    collapseControls,
    layoutScope = "page",
    spans,
    overview,
    selectedSpanId,
    onSelectSpan,
}: {
    collapseControls: TraceCollapseControls;
    layoutScope?: TraceLayoutScope;
    spans: TraceSpan[];
    overview: TraceOverviewItem[];
    selectedSpanId: string | undefined;
    onSelectSpan: (spanId: string) => void;
}): JSX.Element => {
    const { collapsedSpanIds, toggleSpan } = collapseControls;
    const overviewBySpanId = useMemo(
        () => new Map(overview.map((item) => [item.span_id, item])),
        [overview],
    );
    const [viewMode, setViewMode] = useState<SpanViewMode>("tree");
    const expandableSpanIds = useMemo(() => {
        const ids = new Set<string>();
        for (const span of spans) {
            const parentSpanId = span.parent_span_id;
            if (typeof parentSpanId === "string" && parentSpanId !== "") {
                ids.add(parentSpanId);
            }
        }
        return ids;
    }, [spans]);
    const expandedSpanIds = useMemo(() => {
        const next = new Set<string>();
        for (const spanId of expandableSpanIds) {
            if (!collapsedSpanIds.has(spanId)) {
                next.add(spanId);
            }
        }
        return next;
    }, [collapsedSpanIds, expandableSpanIds]);

    const handleTimelineToggle = (pressed: boolean): void => {
        setViewMode(pressed ? "timeline" : "tree");
    };

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="border-border flex items-center justify-end gap-2 border-b px-3 py-2">
                <TraceCollapseAllButton
                    collapseControls={collapseControls}
                    expandableSpanIds={expandableSpanIds}
                />
                <Toggle
                    aria-label="Toggle timeline view"
                    onPressedChange={handleTimelineToggle}
                    pressed={viewMode === "timeline"}
                    size="sm"
                    variant="outline"
                >
                    Timeline
                </Toggle>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
                {viewMode === "timeline" ? (
                    <SpanTimelineList
                        collapsedSpanIds={collapsedSpanIds}
                        layoutScope={layoutScope}
                        onSelectSpan={onSelectSpan}
                        onToggleSpan={toggleSpan}
                        overviewBySpanId={overviewBySpanId}
                        selectedSpanId={selectedSpanId}
                        spans={spans}
                    />
                ) : (
                    <SpanTreeList
                        expandedSpanIds={expandedSpanIds}
                        onSelectSpan={onSelectSpan}
                        onToggleSpan={toggleSpan}
                        overviewBySpanId={overviewBySpanId}
                        selectedSpanId={selectedSpanId}
                        spans={spans}
                    />
                )}
            </div>
        </div>
    );
};
