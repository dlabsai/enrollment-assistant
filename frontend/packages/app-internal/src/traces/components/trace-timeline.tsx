import { useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "@va/shared/lib/utils";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
    type JSX,
    memo,
    type PointerEvent as ReactPointerEvent,
    useCallback,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import type { TraceLayoutScope } from "../lib/trace-layout";
import {
    traceOutcomeRailClass,
    traceTimelineBarClass,
} from "../lib/trace-outcomes";
import {
    buildTraceTimelineScale,
    buildVisibleTraceTimelineRows,
    getTraceTimelineSpanLayout,
    TRACE_TIMELINE_END_PADDING_PX,
    type VisibleTraceTimelineRow,
} from "../lib/trace-timeline";
import type { TraceOutcome } from "../types";
import { TraceOutcomeIndicator } from "./trace-outcome-badge";
import { TraceTreeConnector } from "./trace-tree-connector";

const GUTTER_WIDTH_DEFAULT_PX = 200;
const GUTTER_WIDTH_MIN_PX = 160;
const GUTTER_WIDTH_MAX_PX = 560;
const HEADER_HEIGHT_PX = 32;
const ROW_HEIGHT_PX = 26;
const ROW_OVERSCAN = 16;
const REVEAL_MARGIN_PX = 16;
const REVEAL_LEFT_FRACTION = 0.2;

const getGutterStorageKey = (scope: TraceLayoutScope): string =>
    `internal-trace-timeline-name-width-${scope}`;

const readStoredGutterWidth = (scope: TraceLayoutScope): number => {
    if (typeof window === "undefined") {
        return GUTTER_WIDTH_DEFAULT_PX;
    }
    const storedValue = window.localStorage.getItem(getGutterStorageKey(scope));
    const stored = storedValue === null ? Number.NaN : Number(storedValue);
    return Number.isFinite(stored)
        ? Math.min(
              GUTTER_WIDTH_MAX_PX,
              Math.max(GUTTER_WIDTH_MIN_PX, stored),
          )
        : GUTTER_WIDTH_DEFAULT_PX;
};

export interface TraceTimelineRow {
    id: string;
    label: string;
    subtitle?: string;
    parentId?: string | null;
    depth: number;
    durationLabel: string;
    offsetMs: number;
    durationMs: number;
    outcome?: TraceOutcome | null;
    failedResultCount?: number;
}

interface TraceTimelineProps {
    collapsedSpanIds: ReadonlySet<string>;
    layoutScope?: TraceLayoutScope;
    rows: TraceTimelineRow[];
    selectedSpanId: string | undefined;
    onSelectSpan: (spanId: string) => void;
    onToggleSpan: (spanId: string) => void;
    traceDurationMs: number | undefined;
}

interface TraceTimelineVirtualRowProps {
    chartContentWidth: number;
    gutterWidth: number;
    isSelected: boolean;
    onSelectSpan: (spanId: string) => void;
    onToggleSpan: (spanId: string) => void;
    row: VisibleTraceTimelineRow<TraceTimelineRow> & { isCollapsed: boolean };
    size: number;
    start: number;
    timelineDurationMs: number;
}

const startWindowDrag = (
    onMove: (event: PointerEvent) => void,
    onEnd: () => void,
): void => {
    const handleEnd = (): void => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", handleEnd);
        window.removeEventListener("pointercancel", handleEnd);
        onEnd();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", handleEnd);
    window.addEventListener("pointercancel", handleEnd);
};

const getFiniteDuration = (value: number): number =>
    Number.isFinite(value) ? Math.max(value, 0) : 0;

const getTimelineDuration = (
    rows: TraceTimelineRow[],
    traceDurationMs: number | undefined,
): number => {
    let duration = getFiniteDuration(traceDurationMs ?? 0);
    for (const row of rows) {
        duration = Math.max(
            duration,
            getFiniteDuration(row.offsetMs) +
                getFiniteDuration(row.durationMs),
        );
    }
    return duration;
};

const getRowSurfaceClass = (
    outcome: TraceOutcome | null | undefined,
    isSelected: boolean,
): string => {
    if (isSelected) {
        return "trace-timeline-selection";
    }
    if (outcome === "fail") {
        return "trace-timeline-failure";
    }
    if (outcome === "error") {
        return "trace-timeline-error";
    }
    return "";
};

const TraceTimelineVirtualRow = memo(
    ({
        chartContentWidth,
        gutterWidth,
        isSelected,
        onSelectSpan,
        onToggleSpan,
        row,
        size,
        start,
        timelineDurationMs,
    }: TraceTimelineVirtualRowProps): JSX.Element => {
        const spanLayout = getTraceTimelineSpanLayout(
            row.offsetMs,
            row.durationMs,
            timelineDurationMs,
        );
        const surfaceClass = getRowSurfaceClass(row.outcome, isSelected);

        return (
            <div
                className={cn(
                    "trace-timeline-row absolute top-0 left-0 w-full",
                    surfaceClass,
                )}
                style={{
                    height: `${size}px`,
                    transform: `translateY(${start}px)`,
                }}
            >
                <div
                    className={cn(
                        "trace-timeline-gutter sticky left-0 z-20 flex h-full items-center bg-inherit px-2 text-left",
                        "border-r",
                        surfaceClass === ""
                            ? "border-r-border"
                            : "border-r-transparent",
                    )}
                    style={{ width: `${gutterWidth}px` }}
                >
                    {row.outcome === "fail" || row.outcome === "error" ? (
                        <span
                            aria-hidden
                            className={cn(
                                "pointer-events-none absolute inset-y-0 left-0",
                                traceOutcomeRailClass(row.outcome),
                            )}
                        />
                    ) : undefined}
                    <div className="relative z-10 flex h-full min-w-0 flex-1 items-center">
                        <button
                            className={cn(
                                "flex h-full min-w-0 flex-1 items-center text-left",
                                !row.hasChildren && "-mr-2 pr-2",
                            )}
                            onClick={() => {
                                onSelectSpan(row.id);
                            }}
                            title={
                                row.subtitle === undefined ||
                                row.subtitle.trim() === ""
                                    ? row.label
                                    : `${row.label} · ${row.subtitle}`
                            }
                            type="button"
                        >
                            <TraceTreeConnector
                                ancestorContinuations={
                                    row.ancestorContinuations
                                }
                                depth={row.depth}
                                hasChildren={row.hasChildren}
                                isCollapsed={row.isCollapsed}
                                isLastSibling={row.isLastSibling}
                            />
                            <span className="min-w-0 flex-1 truncate text-xs leading-4">
                                <span className="font-semibold">{row.label}</span>
                                {row.subtitle === undefined ||
                                row.subtitle.trim() === "" ? undefined : (
                                    <span className="text-muted-foreground text-[11px]">
                                        {` · ${row.subtitle}`}
                                    </span>
                                )}
                            </span>
                            <TraceOutcomeIndicator
                                className="ml-1.5"
                                failedResultCount={row.failedResultCount}
                                outcome={row.outcome}
                            />
                        </button>
                        {row.hasChildren ? (
                            <button
                                aria-expanded={!row.isCollapsed}
                                aria-label={
                                    row.isCollapsed
                                        ? `Expand ${row.label}`
                                        : `Collapse ${row.label}`
                                }
                                className="text-muted-foreground hover:text-foreground ml-1 flex size-4 shrink-0 items-center justify-center"
                                onClick={() => {
                                    onToggleSpan(row.id);
                                }}
                                type="button"
                            >
                                {row.isCollapsed ? (
                                    <ChevronRight className="size-3.5" />
                                ) : (
                                    <ChevronDown className="size-3.5" />
                                )}
                            </button>
                        ) : undefined}
                    </div>
                </div>
                <button
                    aria-label={`Select ${row.label} timeline bar`}
                    className="absolute top-0 z-10 h-full bg-transparent text-left"
                    onClick={() => {
                        onSelectSpan(row.id);
                    }}
                    style={{
                        left: `${gutterWidth}px`,
                        width: `${chartContentWidth}px`,
                    }}
                    tabIndex={-1}
                    type="button"
                >
                    <div
                        className="absolute top-1/2 flex -translate-y-1/2 items-center gap-2"
                        style={{ left: `${spanLayout.leftPx}px` }}
                    >
                        <div
                            className={cn(
                                "h-4 rounded-sm",
                                traceTimelineBarClass(row.outcome),
                            )}
                            style={{ width: `${spanLayout.widthPx}px` }}
                        />
                        <span className="text-muted-foreground whitespace-nowrap text-xs tabular-nums">
                            {row.durationLabel}
                        </span>
                    </div>
                </button>
            </div>
        );
    },
);
TraceTimelineVirtualRow.displayName = "TraceTimelineVirtualRow";

const TraceTimelineComponent = ({
    collapsedSpanIds,
    layoutScope = "page",
    rows,
    selectedSpanId,
    onSelectSpan,
    onToggleSpan,
    traceDurationMs,
}: TraceTimelineProps): JSX.Element => {
    const [gutterWidth, setGutterWidth] = useState(() =>
        readStoredGutterWidth(layoutScope),
    );
    const scrollRef = useRef<HTMLDivElement | null>(null);
    const previousSelectedSpanIdRef = useRef<string | undefined>(undefined);

    const timelineDurationMs = useMemo(
        () => getTimelineDuration(rows, traceDurationMs),
        [rows, traceDurationMs],
    );
    const visibleRows = useMemo(
        () =>
            buildVisibleTraceTimelineRows(rows, collapsedSpanIds).map((row) => ({
                ...row,
                isCollapsed: collapsedSpanIds.has(row.id),
            })),
        [collapsedSpanIds, rows],
    );
    const scale = useMemo(
        () => buildTraceTimelineScale(timelineDurationMs),
        [timelineDurationMs],
    );
    const chartContentWidth =
        scale.widthPx + TRACE_TIMELINE_END_PADDING_PX;
    const contentWidth = gutterWidth + chartContentWidth;
    const selectedRowIndex = useMemo(
        () => visibleRows.findIndex((row) => row.id === selectedSpanId),
        [selectedSpanId, visibleRows],
    );

    // eslint-disable-next-line react-hooks/incompatible-library
    const rowVirtualizer = useVirtualizer({
        count: visibleRows.length,
        estimateSize: () => ROW_HEIGHT_PX,
        getItemKey: (index) => visibleRows[index]?.id ?? index,
        getScrollElement: () => scrollRef.current,
        initialOffset:
            HEADER_HEIGHT_PX +
            Math.max(selectedRowIndex, 0) * ROW_HEIGHT_PX,
        overscan: ROW_OVERSCAN,
        paddingStart: HEADER_HEIGHT_PX,
    });
    const virtualRows = rowVirtualizer.getVirtualItems();
    const contentHeight = rowVirtualizer.getTotalSize();

    const handleGutterResize = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>): void => {
            event.preventDefault();
            const startX = event.clientX;
            const startWidth = gutterWidth;
            let nextWidth = startWidth;
            startWindowDrag(
                (moveEvent) => {
                    nextWidth = Math.min(
                        GUTTER_WIDTH_MAX_PX,
                        Math.max(
                            GUTTER_WIDTH_MIN_PX,
                            startWidth + moveEvent.clientX - startX,
                        ),
                    );
                    setGutterWidth(nextWidth);
                },
                () => {
                    window.localStorage.setItem(
                        getGutterStorageKey(layoutScope),
                        String(nextWidth),
                    );
                },
            );
        },
        [gutterWidth, layoutScope],
    );

    useLayoutEffect(() => {
        if (selectedSpanId === undefined) {
            previousSelectedSpanIdRef.current = undefined;
            return;
        }
        if (selectedSpanId === previousSelectedSpanIdRef.current) {
            return;
        }

        const scrollElement = scrollRef.current;
        if (selectedRowIndex === -1 || scrollElement === null) {
            return;
        }

        const isInitialSelection =
            previousSelectedSpanIdRef.current === undefined;
        previousSelectedSpanIdRef.current = selectedSpanId;
        const rowTop =
            HEADER_HEIGHT_PX + selectedRowIndex * ROW_HEIGHT_PX;
        let top = scrollElement.scrollTop;
        if (isInitialSelection) {
            top =
                rowTop -
                HEADER_HEIGHT_PX -
                (scrollElement.clientHeight -
                    HEADER_HEIGHT_PX -
                    ROW_HEIGHT_PX) /
                    2;
        } else if (
            rowTop <
            scrollElement.scrollTop + HEADER_HEIGHT_PX
        ) {
            top = rowTop - HEADER_HEIGHT_PX;
        } else if (
            rowTop + ROW_HEIGHT_PX >
            scrollElement.scrollTop + scrollElement.clientHeight
        ) {
            top = rowTop + ROW_HEIGHT_PX - scrollElement.clientHeight;
        }

        const selectedRow = visibleRows[selectedRowIndex];
        const barStart = getTraceTimelineSpanLayout(
            selectedRow?.offsetMs ?? 0,
            selectedRow?.durationMs ?? 0,
            timelineDurationMs,
        ).leftPx;
        const chartViewportWidth = Math.max(
            scrollElement.clientWidth - gutterWidth,
            1,
        );
        let left = scrollElement.scrollLeft;
        if (
            barStart < scrollElement.scrollLeft + REVEAL_MARGIN_PX ||
            barStart >
                scrollElement.scrollLeft +
                    chartViewportWidth -
                    REVEAL_MARGIN_PX
        ) {
            left = Math.max(
                0,
                barStart - chartViewportWidth * REVEAL_LEFT_FRACTION,
            );
        }

        const clampedTop = Math.max(0, top);
        if (
            clampedTop === scrollElement.scrollTop &&
            left === scrollElement.scrollLeft
        ) {
            return;
        }
        scrollElement.scrollTo({
            top: clampedTop,
            left,
            behavior: isInitialSelection ? "auto" : "smooth",
        });
    }, [
        gutterWidth,
        selectedRowIndex,
        visibleRows,
        selectedSpanId,
        timelineDurationMs,
    ]);

    if (rows.length === 0) {
        return (
            <div className="text-muted-foreground px-4 py-3 text-xs">
                No timed spans recorded for this trace.
            </div>
        );
    }

    return (
        <div className="relative h-full min-h-0 overflow-hidden">
            <div
                aria-label="Trace timeline"
                className="h-full overflow-auto overscroll-contain"
                ref={scrollRef}
                role="region"
            >
                <div
                    className="relative min-w-full"
                    style={{
                        height: `${contentHeight}px`,
                        width: `${contentWidth}px`,
                    }}
                >
                    <div className="bg-background sticky top-0 z-30 h-8 w-full">
                        <div
                            className="bg-background text-muted-foreground sticky left-0 z-40 flex h-full items-center border-r px-2 text-xs font-medium"
                            style={{ width: `${gutterWidth}px` }}
                        >
                            Name
                        </div>
                        <div
                            className="absolute inset-y-0"
                            style={{
                                left: `${gutterWidth}px`,
                                width: `${chartContentWidth}px`,
                            }}
                        >
                            {scale.ticks.map((tick) => (
                                <div
                                    className={cn(
                                        "absolute inset-y-0",
                                        tick.offsetMs > 0 &&
                                            "border-border-contrast border-l",
                                    )}
                                    key={tick.offsetMs}
                                    style={{ left: `${tick.leftPx}px` }}
                                >
                                    <span className="text-muted-foreground absolute top-1 left-2 whitespace-nowrap text-[10px] tabular-nums">
                                        {tick.label}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                    {virtualRows.map((virtualRow) => {
                        const row = visibleRows[virtualRow.index];
                        if (row === undefined) {
                            return null;
                        }
                        return (
                            <TraceTimelineVirtualRow
                                chartContentWidth={chartContentWidth}
                                gutterWidth={gutterWidth}
                                isSelected={row.id === selectedSpanId}
                                key={row.id}
                                onSelectSpan={onSelectSpan}
                                onToggleSpan={onToggleSpan}
                                row={row}
                                size={virtualRow.size}
                                start={virtualRow.start}
                                timelineDurationMs={timelineDurationMs}
                            />
                        );
                    })}
                </div>
            </div>
            <div
                aria-label="Resize name column"
                aria-orientation="vertical"
                className="hover:bg-primary/40 active:bg-primary/40 absolute inset-y-0 z-50 w-2 -translate-x-1/2 cursor-col-resize"
                onPointerDown={handleGutterResize}
                role="separator"
                style={{ left: `${gutterWidth}px` }}
            />
        </div>
    );
};

export const TraceTimeline = memo(TraceTimelineComponent);
TraceTimeline.displayName = "TraceTimeline";
