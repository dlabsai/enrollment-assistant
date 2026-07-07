import { Streamdown } from "@va/shared/components/streamdown";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "@va/shared/components/ui/tabs";
import { Toggle } from "@va/shared/components/ui/toggle";
import {
    ChevronDown,
    ChevronRight,
    ChevronsDown,
    ChevronsUp,
    FileText,
    Info,
} from "lucide-react";
import {
    type JSX,
    memo,
    useCallback,
    useEffect,
    useMemo,
    useState,
} from "react";
import { JSONTree, type ShouldExpandNodeInitially } from "react-json-tree";

import { LoadingState } from "@/components/page-state";

import {
    buildSpanTree,
    getStringAttribute,
    parseJsonRecursively,
} from "../lib/trace-utils";
import {
    buildSpanHierarchy,
    formatSpanDuration,
    getSpanTimelineLayout,
    getTraceTimeRange,
    jsonTreeTheme,
    shouldExpandJsonNode,
    type SpanTreeNode,
} from "../lib/trace-view-utils";
import type { TraceDetail, TraceSpan } from "../types";
import { TraceTurnDebugView } from "./trace-turn-debug-view";

interface TraceDetailPanelProps {
    detail: TraceDetail | undefined;
    loading: boolean;
    error: string | undefined;
    selectedSpanId?: string;
    view?: TraceDetailView;
    onViewChange?: (view: TraceDetailView) => void;
    onSpanChange?: (spanId: string | undefined) => void;
    onSpanSync?: (spanId: string | undefined) => void;
}

type SpanViewMode = "tree" | "timeline";
type TraceDetailView = "span" | "summary";

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

const SpanNavigator = memo(
    ({
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
    },
);
SpanNavigator.displayName = "SpanNavigator";

const MarkdownContent = ({ content }: { content: string }): JSX.Element => (
    <Streamdown className="max-w-none break-words">{content}</Streamdown>
);

const isJsonString = (value: string): boolean => {
    const trimmed = value.trim();
    return trimmed.startsWith("{") || trimmed.startsWith("[");
};

const createJsonValueRenderer = (
    onPreview: (content: string) => void,
): ((
    displayValue: unknown,
    rawValue: unknown,
    ...keyPath: (string | number)[]
) => JSX.Element) => {
    const renderer = (
        displayValue: unknown,
        rawValue: unknown,
        ...keyPath: (string | number)[]
    ): JSX.Element => {
        const [key] = keyPath;
        const isContentKey = key === "content";
        if (
            isContentKey &&
            typeof rawValue === "string" &&
            rawValue.trim() !== "" &&
            !isJsonString(rawValue)
        ) {
            return (
                <span className="inline-flex items-start gap-1">
                    <span className="whitespace-pre-wrap">
                        {String(displayValue)}
                    </span>
                    <button
                        className="text-muted-foreground hover:text-foreground"
                        onClick={(event) => {
                            event.stopPropagation();
                            onPreview(rawValue);
                        }}
                        type="button"
                    >
                        <FileText className="size-3" />
                    </button>
                </span>
            );
        }
        return <span>{String(displayValue)}</span>;
    };
    renderer.displayName = "RawJsonValueRenderer";
    return renderer;
};

const SpanRaw = memo(
    ({
        span,
        parseJsonStrings,
        expandAll,
    }: {
        span: TraceSpan;
        parseJsonStrings: boolean;
        expandAll: boolean;
    }): JSX.Element => {
        const data = useMemo(
            () => (parseJsonStrings ? parseJsonRecursively(span) : span),
            [parseJsonStrings, span],
        );
        const [dialogContent, setDialogContent] = useState<
            string | undefined
        >();
        const valueRenderer = useMemo(
            () => createJsonValueRenderer(setDialogContent),
            [setDialogContent],
        );
        const shouldExpand: ShouldExpandNodeInitially = useCallback(
            (keyPath, dataValue, level) =>
                expandAll
                    ? true
                    : shouldExpandJsonNode(keyPath, dataValue, level),
            [expandAll],
        );
        const treeKey = expandAll ? "raw-json-expanded" : "raw-json-collapsed";

        return (
            <div className="bg-muted/30 rounded-md border p-3 text-sm">
                <Dialog
                    onOpenChange={(open) => {
                        if (!open) {
                            setDialogContent(undefined);
                        }
                    }}
                    open={dialogContent !== undefined}
                >
                    <JSONTree
                        data={data}
                        key={treeKey}
                        shouldExpandNodeInitially={shouldExpand}
                        theme={jsonTreeTheme}
                        valueRenderer={valueRenderer}
                    />
                    {dialogContent === undefined ? undefined : (
                        <DialogContent className="w-[88vw] max-w-[48rem] sm:max-w-[48rem]">
                            <DialogHeader>
                                <DialogTitle>Markdown preview</DialogTitle>
                            </DialogHeader>
                            <div className="max-h-[70vh] overflow-auto">
                                <MarkdownContent content={dialogContent} />
                            </div>
                        </DialogContent>
                    )}
                </Dialog>
            </div>
        );
    },
);
SpanRaw.displayName = "SpanRaw";

const traceViewStorageKey = "internal-trace-detail-view";
const rawJsonParsingStorageKey = "internal-trace-raw-json-parse";

const isTraceDetailView = (value: string): value is TraceDetailView =>
    value === "span" || value === "summary";

export const TraceDetailPanel = ({
    detail,
    loading,
    error,
    selectedSpanId: externalSpanId,
    view,
    onViewChange,
    onSpanChange,
    onSpanSync,
}: TraceDetailPanelProps): JSX.Element => {
    const [localSpanId, setLocalSpanId] = useState<string | undefined>();
    const [localActiveView, setLocalActiveView] = useState<TraceDetailView>(() => {
        if (typeof window === "undefined") {
            return "span";
        }
        const stored = window.localStorage.getItem(traceViewStorageKey);
        if (stored === null) {
            return "span";
        }
        const trimmed = stored.trim();
        if (trimmed === "" || !isTraceDetailView(trimmed)) {
            return "span";
        }
        return trimmed;
    });
    const activeView = view ?? localActiveView;
    const [parseRawJsonStrings, setParseRawJsonStrings] = useState(() => {
        if (typeof window === "undefined") {
            return false;
        }
        const stored = window.localStorage.getItem(rawJsonParsingStorageKey);
        if (stored === null) {
            return false;
        }
        return stored.trim() === "true";
    });
    const [rawExpandAll, setRawExpandAll] = useState(false);
    const [mountedViews, setMountedViews] = useState<Set<TraceDetailView>>(
        () => new Set([activeView]),
    );

    const spans = useMemo(() => detail?.spans ?? [], [detail]);

    const selectedSpanId = externalSpanId ?? localSpanId;

    const activeSpanId = useMemo(() => {
        if (
            selectedSpanId !== undefined &&
            spans.some((span) => span.span_id === selectedSpanId)
        ) {
            return selectedSpanId;
        }
        return spans[0]?.span_id;
    }, [selectedSpanId, spans]);

    const selectedSpan = spans.find((span) => span.span_id === activeSpanId);

    const handleSpanSelect = useCallback(
        (spanId: string): void => {
            setLocalSpanId(spanId);
            onSpanChange?.(spanId);
        },
        [onSpanChange],
    );

    const handleViewChange = useCallback(
        (value: string): void => {
            const nextView = isTraceDetailView(value) ? value : "span";
            setLocalActiveView(nextView);
            setMountedViews((previous) => {
                if (previous.has(nextView)) {
                    return previous;
                }
                const next = new Set(previous);
                next.add(nextView);
                return next;
            });
            onViewChange?.(nextView);
        },
        [onViewChange],
    );

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        window.localStorage.setItem(traceViewStorageKey, localActiveView);
    }, [localActiveView]);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        window.localStorage.setItem(
            rawJsonParsingStorageKey,
            String(parseRawJsonStrings),
        );
    }, [parseRawJsonStrings]);

    useEffect(() => {
        if (!onSpanSync || externalSpanId !== undefined) {
            return;
        }
        if (spans.length === 0) {
            return;
        }
        onSpanSync(spans[0]?.span_id);
    }, [externalSpanId, onSpanSync, spans]);

    let content: JSX.Element = (
        <div className="text-muted-foreground flex h-full items-center justify-center gap-2 text-sm">
            <Info className="size-4" /> Select a trace to view spans
        </div>
    );

    if (loading) {
        content = <LoadingState />;
    } else if (error !== undefined) {
        content = (
            <div className="text-destructive flex h-full items-center justify-center">
                {error}
            </div>
        );
    } else if (detail !== undefined) {
        const spanDetailContent = (
            <ResizablePanelGroup
                className="h-full min-h-0 min-w-0"
                id="trace-detail-raw-layout"
                orientation="horizontal"
            >
                <ResizablePanel
                    className="min-h-0 min-w-0"
                    defaultSize="42%"
                    id="trace-detail-raw-spans-panel"
                    minSize="30%"
                >
                    <SpanNavigator
                        onSelectSpan={handleSpanSelect}
                        selectedSpanId={activeSpanId}
                        spans={spans}
                    />
                </ResizablePanel>
                <ResizableHandle withHandle />
                <ResizablePanel
                    className="min-h-0 min-w-0"
                    defaultSize="58%"
                    id="trace-detail-raw-details-panel"
                    minSize="40%"
                >
                    <div className="h-full min-h-0 min-w-0 overflow-auto">
                        {selectedSpan === undefined ? (
                            <div className="text-muted-foreground flex h-full items-center justify-center">
                                Select a span to see details.
                            </div>
                        ) : (
                            <div className="space-y-4 px-4 py-4">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div>
                                        <div className="text-sm font-semibold">
                                            {selectedSpan.name}
                                        </div>
                                        <div className="text-muted-foreground text-xs">
                                            {formatSpanDuration(selectedSpan)}
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <Toggle
                                            onPressedChange={() => {
                                                setRawExpandAll(
                                                    (value) => !value,
                                                );
                                            }}
                                            pressed={rawExpandAll}
                                            size="sm"
                                            variant="outline"
                                        >
                                            Expand all nodes
                                        </Toggle>
                                        <Toggle
                                            aria-label="Toggle JSON string parsing"
                                            onPressedChange={
                                                setParseRawJsonStrings
                                            }
                                            pressed={parseRawJsonStrings}
                                            size="sm"
                                            variant="outline"
                                        >
                                            Parse JSON strings
                                        </Toggle>
                                    </div>
                                </div>
                                <SpanRaw
                                    expandAll={rawExpandAll}
                                    parseJsonStrings={parseRawJsonStrings}
                                    span={selectedSpan}
                                />
                            </div>
                        )}
                    </div>
                </ResizablePanel>
            </ResizablePanelGroup>
        );

        content = (
            <Tabs
                className="h-full min-h-0"
                onValueChange={handleViewChange}
                value={activeView}
            >
                <div className="border-border flex items-center justify-between border-b px-4 py-2">
                    <div className="text-muted-foreground text-xs uppercase">
                        Trace View
                    </div>
                    <TabsList>
                        <TabsTrigger value="span">Raw</TabsTrigger>
                        <TabsTrigger value="summary">Overview</TabsTrigger>
                    </TabsList>
                </div>
                <TabsContent
                    className="min-h-0 flex-1 data-[hidden]:hidden"
                    keepMounted={mountedViews.has("span") ? true : undefined}
                    value="span"
                >
                    {spanDetailContent}
                </TabsContent>
                <TabsContent
                    className="min-h-0 flex-1 data-[hidden]:hidden"
                    keepMounted={mountedViews.has("summary") ? true : undefined}
                    value="summary"
                >
                    <TraceTurnDebugView
                        detail={detail}
                        error={undefined}
                        loading={false}
                        selectedSpanId={externalSpanId}
                        summaryOnly
                    />
                </TabsContent>
            </Tabs>
        );
    }

    return <div className="h-full min-h-0 overflow-hidden">{content}</div>;
};
