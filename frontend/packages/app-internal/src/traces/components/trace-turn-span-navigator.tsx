import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import { Toggle } from "@va/shared/components/ui/toggle";
import {
    ChevronDown,
    ChevronRight,
    ChevronsDown,
    ChevronsUp,
} from "lucide-react";
import { type JSX, useMemo, useState } from "react";

import { buildSpanTree, getStringAttribute } from "../lib/trace-utils";
import {
    buildSpanHierarchy,
    formatSpanDuration,
    getSpanTimelineLayout,
    getTraceTimeRange,
    type SpanTreeNode,
} from "../lib/trace-view-utils";
import type { TraceSpan } from "../types";

type SpanViewMode = "tree" | "timeline";

const SpanTimelineList = ({
    spans,
    selectedSpanId,
    onSelectSpan,
}: {
    spans: TraceSpan[];
    selectedSpanId: string | undefined;
    onSelectSpan: (spanId: string) => void;
}): JSX.Element => {
    const flattened = useMemo(() => buildSpanTree(spans), [spans]);
    const { end: traceEnd, start: traceStart } = useMemo(
        () => getTraceTimeRange(spans),
        [spans],
    );

    return (
        <div className="px-4 py-3">
            {flattened.map(({ span, depth }) => {
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
                const offsetPct = timelineLayout?.offsetPct ?? 0;
                const widthPct = timelineLayout?.widthPct ?? 2;

                const labelParts = [agentName, model].filter(
                    (item): item is string =>
                        typeof item === "string" && item.trim() !== "",
                );

                return (
                    <button
                        className="hover:border-primary/50 hover:bg-primary/10 data-[selected=true]:border-primary data-[selected=true]:bg-primary/15 data-[selected=true]:ring-primary/30 flex w-full flex-col gap-2 rounded-none border border-transparent px-2 py-2 text-left transition-none data-[selected=true]:shadow-sm data-[selected=true]:ring-1"
                        data-selected={selectedSpanId === span.span_id}
                        key={span.span_id}
                        onClick={() => {
                            onSelectSpan(span.span_id);
                        }}
                        type="button"
                    >
                        <div className="flex items-start justify-between gap-2">
                            <div className="flex min-w-0 flex-1 flex-col gap-1">
                                <div
                                    className="text-sm font-medium break-words"
                                    style={{
                                        paddingLeft: `${depth * 16}px`,
                                    }}
                                >
                                    {span.name}
                                </div>
                                <div
                                    className="text-muted-foreground text-xs break-words"
                                    style={{
                                        paddingLeft: `${depth * 16}px`,
                                    }}
                                >
                                    {labelParts.join(" · ")}
                                </div>
                            </div>
                            <div className="text-muted-foreground text-xs tabular-nums">
                                {formatSpanDuration(span)}
                            </div>
                        </div>
                        <div className="bg-muted relative h-1 overflow-hidden rounded">
                            <div
                                className="bg-primary absolute inset-y-0 rounded"
                                style={{
                                    left: `${offsetPct}%`,
                                    width: `${widthPct}%`,
                                }}
                            />
                        </div>
                        {span.status_code === "ERROR" ? (
                            <Badge variant="destructive">Error</Badge>
                        ) : undefined}
                    </button>
                );
            })}
        </div>
    );
};

const SpanTreeList = ({
    spans,
    selectedSpanId,
    expandedSpanIds,
    onSelectSpan,
    onToggleSpan,
}: {
    spans: TraceSpan[];
    selectedSpanId: string | undefined;
    expandedSpanIds: Set<string>;
    onSelectSpan: (spanId: string) => void;
    onToggleSpan: (spanId: string) => void;
}): JSX.Element => {
    const tree = useMemo(() => buildSpanHierarchy(spans), [spans]);

    const handleSpanSelect = (spanId: string): void => {
        onSelectSpan(spanId);
    };

    const renderNodes = (nodes: SpanTreeNode[], depth: number): JSX.Element[] =>
        nodes.map((node) => {
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
                    typeof item === "string" && item.trim() !== "",
            );
            const hasChildren = children.length > 0;
            const isExpanded = expandedSpanIds.has(span.span_id);

            return (
                <div key={span.span_id}>
                    <div
                        className="hover:border-primary/50 hover:bg-primary/10 data-[selected=true]:border-primary data-[selected=true]:bg-primary/15 data-[selected=true]:ring-primary/30 flex w-full flex-col gap-2 rounded-none border border-transparent px-2 py-2 text-left transition-none data-[selected=true]:shadow-sm data-[selected=true]:ring-1"
                        data-selected={selectedSpanId === span.span_id}
                        onClick={() => {
                            handleSpanSelect(span.span_id);
                        }}
                        onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                handleSpanSelect(span.span_id);
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
                        {span.status_code === "ERROR" ? (
                            <Badge variant="destructive">Error</Badge>
                        ) : undefined}
                    </div>
                    {hasChildren && isExpanded ? (
                        <div>{renderNodes(children, depth + 1)}</div>
                    ) : undefined}
                </div>
            );
        });

    return <div className="px-4 py-3">{renderNodes(tree, 0)}</div>;
};

export const SpanNavigator = ({
    spans,
    selectedSpanId,
    onSelectSpan,
}: {
    spans: TraceSpan[];
    selectedSpanId: string | undefined;
    onSelectSpan: (spanId: string) => void;
}): JSX.Element => {
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
    const [collapsedSpanIds, setCollapsedSpanIds] = useState<Set<string>>(
        () => new Set(),
    );

    const expandedSpanIds = useMemo(() => {
        const next = new Set<string>();
        for (const spanId of expandableSpanIds) {
            if (!collapsedSpanIds.has(spanId)) {
                next.add(spanId);
            }
        }
        return next;
    }, [collapsedSpanIds, expandableSpanIds]);

    const hasExpandableNodes = expandableSpanIds.size > 0;
    const hasCollapsedNodes = expandedSpanIds.size < expandableSpanIds.size;

    const toggleSpan = (spanId: string): void => {
        setCollapsedSpanIds((previous) => {
            const next = new Set(previous);
            if (next.has(spanId)) {
                next.delete(spanId);
            } else {
                next.add(spanId);
            }
            return next;
        });
    };

    const handleTimelineToggle = (pressed: boolean): void => {
        setViewMode(pressed ? "timeline" : "tree");
    };

    const handleExpandCollapseAll = (): void => {
        if (!hasExpandableNodes) {
            return;
        }
        if (hasCollapsedNodes) {
            setCollapsedSpanIds(new Set());
        } else {
            setCollapsedSpanIds(new Set(expandableSpanIds));
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="border-border flex items-center justify-between border-b px-3 py-2">
                <div className="text-muted-foreground text-xs uppercase">
                    Spans
                </div>
                <div className="flex items-center gap-2">
                    {viewMode === "tree" ? (
                        <Button
                            aria-label={
                                hasCollapsedNodes
                                    ? "Expand all spans"
                                    : "Collapse all spans"
                            }
                            disabled={!hasExpandableNodes}
                            onClick={handleExpandCollapseAll}
                            size="icon-sm"
                            type="button"
                            variant="outline"
                        >
                            {hasCollapsedNodes ? (
                                <ChevronsDown className="size-4" />
                            ) : (
                                <ChevronsUp className="size-4" />
                            )}
                        </Button>
                    ) : undefined}
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
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
                {viewMode === "timeline" ? (
                    <SpanTimelineList
                        onSelectSpan={onSelectSpan}
                        selectedSpanId={selectedSpanId}
                        spans={spans}
                    />
                ) : (
                    <SpanTreeList
                        expandedSpanIds={expandedSpanIds}
                        onSelectSpan={onSelectSpan}
                        onToggleSpan={toggleSpan}
                        selectedSpanId={selectedSpanId}
                        spans={spans}
                    />
                )}
            </div>
        </div>
    );
};
