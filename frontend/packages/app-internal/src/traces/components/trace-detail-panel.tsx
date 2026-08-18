import { Streamdown } from "@va/shared/components/streamdown";
import { Badge } from "@va/shared/components/ui/badge";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "@va/shared/components/ui/tabs";
import { Toggle } from "@va/shared/components/ui/toggle";
import { FileText, Info } from "lucide-react";
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

import { formatUsdCost } from "../../lib/number-format";
import { useTraceCollapse } from "../hooks/use-trace-collapse";
import type { TraceLayoutScope } from "../lib/trace-layout";
import {
    getAggregateFailedResultCount,
    getTraceSpanOutcome,
} from "../lib/trace-outcomes";
import { parseJsonRecursively } from "../lib/trace-utils";
import {
    formatSpanDuration,
    jsonTreeTheme,
    shouldExpandJsonNode,
    TRACE_TEXT_PREVIEW_LENGTH,
} from "../lib/trace-view-utils";
import type { TraceDetail, TraceSpan } from "../types";
import { TraceOutcomeBadge } from "./trace-outcome-badge";
import { TraceSplitLayout } from "./trace-split-layout";
import { TraceTurnDebugView } from "./trace-turn-debug-view";
import { SpanNavigator } from "./trace-turn-span-navigator";

interface TraceDetailPanelProps {
    detail: TraceDetail | undefined;
    loading: boolean;
    error: string | undefined;
    selectedSpanId?: string;
    view?: TraceDetailView;
    onViewChange?: (view: TraceDetailView) => void;
    onSpanChange?: (spanId: string) => void | Promise<void>;
    onSpanSync?: (spanId: string | undefined) => void;
    layoutScope?: TraceLayoutScope;
}

type TraceDetailView = "span" | "summary";

const MarkdownContent = ({ content }: { content: string }): JSX.Element => (
    <Streamdown className="max-w-none break-words">{content}</Streamdown>
);

const isJsonLikeString = (value: string): boolean => {
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
        const isLongString =
            typeof rawValue === "string" &&
            rawValue.length > TRACE_TEXT_PREVIEW_LENGTH;
        const canPreview =
            typeof rawValue === "string" &&
            rawValue.trim() !== "" &&
            (isLongString || (isContentKey && !isJsonLikeString(rawValue)));
        if (canPreview) {
            const preview = isLongString
                ? `${rawValue.slice(0, TRACE_TEXT_PREVIEW_LENGTH)}…`
                : String(displayValue);
            return (
                <span className="inline-flex items-start gap-1">
                    <span className="whitespace-pre-wrap">{preview}</span>
                    <button
                        aria-label="View full value"
                        className="text-muted-foreground hover:text-foreground shrink-0"
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
                                <DialogTitle>
                                    {isJsonLikeString(dialogContent)
                                        ? "Raw value"
                                        : "Markdown preview"}
                                </DialogTitle>
                            </DialogHeader>
                            <div className="max-h-[70vh] overflow-auto">
                                {isJsonLikeString(dialogContent) ? (
                                    <pre className="text-xs break-words whitespace-pre-wrap">
                                        {dialogContent}
                                    </pre>
                                ) : (
                                    <MarkdownContent content={dialogContent} />
                                )}
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
    layoutScope = "page",
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

    const spans = useMemo(() => detail?.spans ?? [], [detail]);
    const spansById = useMemo(
        () => new Map(spans.map((span) => [span.span_id, span])),
        [spans],
    );
    const overview = useMemo(() => detail?.overview ?? [], [detail]);
    const overviewBySpanId = useMemo(
        () => new Map(overview.map((item) => [item.span_id, item])),
        [overview],
    );
    const collapseControls = useTraceCollapse();

    const selectedSpanId = localSpanId ?? externalSpanId;
    const activeSpanId =
        selectedSpanId !== undefined && spansById.has(selectedSpanId)
            ? selectedSpanId
            : spans[0]?.span_id;

    const selectedSpan =
        activeSpanId === undefined ? undefined : spansById.get(activeSpanId);
    const selectedOverviewItem =
        activeSpanId === undefined ? undefined : overviewBySpanId.get(activeSpanId);
    const selectedOutcome = getTraceSpanOutcome(
        selectedSpan,
        selectedOverviewItem,
    );

    const traceCost = detail?.total_cost;
    const traceCostLabel =
        traceCost === undefined || traceCost === null
            ? undefined
            : formatUsdCost(traceCost);

    const handleSpanSelect = useCallback(
        (spanId: string): void => {
            setLocalSpanId(spanId);
            const navigation = onSpanChange?.(spanId);
            if (navigation !== undefined) {
                const clearOptimisticSelection = (): void => {
                    setLocalSpanId((current) =>
                        current === spanId ? undefined : current,
                    );
                };
                void navigation.then(
                    clearOptimisticSelection,
                    clearOptimisticSelection,
                );
            }
        },
        [onSpanChange],
    );

    const handleViewChange = useCallback(
        (value: string): void => {
            const nextView = isTraceDetailView(value) ? value : "span";
            setLocalActiveView(nextView);
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
            <TraceSplitLayout
                detail={
                    <div className="h-full min-h-0 min-w-0 overflow-auto">
                        {selectedSpan === undefined ? (
                            <div className="text-muted-foreground flex h-full items-center justify-center">
                                Select a span to see details.
                            </div>
                        ) : (
                            <div className="space-y-4 px-4 py-4">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div className="flex flex-wrap items-start gap-2">
                                        <div>
                                            <div className="text-sm font-semibold">
                                                {selectedSpan.name}
                                            </div>
                                            <div className="text-muted-foreground text-xs">
                                                {formatSpanDuration(selectedSpan)}
                                            </div>
                                        </div>
                                        <TraceOutcomeBadge
                                            failedResultCount={getAggregateFailedResultCount(
                                                selectedOverviewItem,
                                            )}
                                            outcome={selectedOutcome}
                                        />
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
                }
                navigation={
                    <SpanNavigator
                        collapseControls={collapseControls}
                        layoutScope={layoutScope}
                        onSelectSpan={handleSpanSelect}
                        overview={overview}
                        selectedSpanId={activeSpanId}
                        spans={spans}
                    />
                }
                scope={layoutScope}
            />
        );

        content = (
            <Tabs
                className="h-full min-h-0"
                onValueChange={handleViewChange}
                value={activeView}
            >
                <div className="border-border flex items-center gap-2 border-b px-4 py-2">
                    {traceCostLabel === undefined ? undefined : (
                        <Badge variant="secondary">{traceCostLabel}</Badge>
                    )}
                    <TabsList className="ml-auto">
                        <TabsTrigger value="span">Raw</TabsTrigger>
                        <TabsTrigger value="summary">Overview</TabsTrigger>
                    </TabsList>
                </div>
                <TabsContent
                    className="min-h-0 flex-1"
                    value="span"
                >
                    {spanDetailContent}
                </TabsContent>
                <TabsContent
                    className="min-h-0 flex-1"
                    value="summary"
                >
                    <TraceTurnDebugView
                        collapseControls={collapseControls}
                        detail={detail}
                        error={undefined}
                        key={detail.trace_id}
                        layoutScope={layoutScope}
                        loading={false}
                        onSpanChange={handleSpanSelect}
                        selectedSpanId={activeSpanId}
                    />
                </TabsContent>
            </Tabs>
        );
    }

    return <div className="h-full min-h-0 overflow-hidden">{content}</div>;
};
