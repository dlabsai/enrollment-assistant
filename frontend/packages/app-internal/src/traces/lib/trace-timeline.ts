export const TRACE_TIMELINE_END_PADDING_PX = 300;

const TRACE_TIMELINE_SCALE_WIDTH_PX = 900;
const TARGET_TICK_SPACING_PX = 100;
const MINIMUM_BAR_WIDTH_PX = 4;
const NICE_INTERVAL_MULTIPLIERS = [1, 1.5, 2, 2.5, 5, 10];

interface TraceTimelineSpanLayout {
    leftPx: number;
    widthPx: number;
}

interface TraceTimelineTick {
    label: string;
    leftPx: number;
    offsetMs: number;
}

interface TraceTimelineScale {
    ticks: TraceTimelineTick[];
    widthPx: number;
}

interface TraceTimelineTreeRow {
    id: string;
    parentId?: string | null;
    depth: number;
}

export type VisibleTraceTimelineRow<T extends TraceTimelineTreeRow> = T & {
    ancestorContinuations: boolean[];
    hasChildren: boolean;
    isLastSibling: boolean;
};

const resolveTimelineParents = (
    rows: TraceTimelineTreeRow[],
): Map<string, string | null> => {
    const rowIds = new Set(rows.map((row) => row.id));
    const parents = new Map<string, string | null>();
    const depthStack: string[] = [];

    for (const row of rows) {
        const explicitParent =
            typeof row.parentId === "string" &&
            row.parentId !== row.id &&
            rowIds.has(row.parentId)
                ? row.parentId
                : null;
        const inferredParent =
            row.parentId === undefined && row.depth > 0
                ? (depthStack[row.depth - 1] ?? null)
                : null;
        parents.set(
            row.id,
            row.parentId === undefined ? inferredParent : explicitParent,
        );
        depthStack[row.depth] = row.id;
        depthStack.length = row.depth + 1;
    }

    const visitState = new Map<string, "visiting" | "visited">();
    const breakParentCycles = (rowId: string): void => {
        visitState.set(rowId, "visiting");
        const parentId = parents.get(rowId);
        if (parentId !== null && parentId !== undefined) {
            const parentState = visitState.get(parentId);
            if (parentState === "visiting") {
                parents.set(rowId, null);
            } else if (parentState !== "visited") {
                breakParentCycles(parentId);
            }
        }
        visitState.set(rowId, "visited");
    };
    for (const rowId of rowIds) {
        if (visitState.get(rowId) !== "visited") {
            breakParentCycles(rowId);
        }
    }

    return parents;
};

export const buildVisibleTraceTimelineRows = <T extends TraceTimelineTreeRow>(
    rows: T[],
    collapsedRowIds: ReadonlySet<string>,
): VisibleTraceTimelineRow<T>[] => {
    const parents = resolveTimelineParents(rows);
    const childrenByParent = new Map<string | null, T[]>();
    for (const row of rows) {
        const parentId = parents.get(row.id) ?? null;
        const siblings = childrenByParent.get(parentId) ?? [];
        siblings.push(row);
        childrenByParent.set(parentId, siblings);
    }

    const visible: VisibleTraceTimelineRow<T>[] = [];
    const visited = new Set<string>();
    const hideDescendants = (descendants: T[]): void => {
        for (const descendant of descendants) {
            if (!visited.has(descendant.id)) {
                visited.add(descendant.id);
                hideDescendants(childrenByParent.get(descendant.id) ?? []);
            }
        }
    };
    const visit = (
        siblings: T[],
        depth: number,
        ancestorContinuations: boolean[],
    ): void => {
        for (const [index, row] of siblings.entries()) {
            if (!visited.has(row.id)) {
                visited.add(row.id);
                const children = childrenByParent.get(row.id) ?? [];
                const isLastSibling = index === siblings.length - 1;
                visible.push({
                    ...row,
                    depth,
                    ancestorContinuations,
                    hasChildren: children.length > 0,
                    isLastSibling,
                });
                if (collapsedRowIds.has(row.id)) {
                    hideDescendants(children);
                } else {
                    visit(
                        children,
                        depth + 1,
                        depth === 0
                            ? []
                            : [...ancestorContinuations, !isLastSibling],
                    );
                }
            }
        }
    };

    visit(childrenByParent.get(null) ?? [], 0, []);
    return visible;
};

const normalizeDuration = (durationMs: number | undefined): number =>
    durationMs === undefined || !Number.isFinite(durationMs)
        ? 0
        : Math.max(durationMs, 0);

const getNiceTickInterval = (durationMs: number): number => {
    const targetInterval =
        durationMs /
        (TRACE_TIMELINE_SCALE_WIDTH_PX / TARGET_TICK_SPACING_PX);
    if (targetInterval === 0) {
        return durationMs;
    }
    const magnitude = 10 ** Math.floor(Math.log10(targetInterval));
    if (magnitude === 0) {
        return durationMs;
    }
    const normalized = targetInterval / magnitude;
    const multiplier =
        NICE_INTERVAL_MULTIPLIERS.find(
            (candidate) => normalized <= candidate,
        ) ?? 10;
    return multiplier * magnitude;
};

const formatDecimal = (value: number, fractionDigits: number): string =>
    Number.isInteger(value)
        ? String(value)
        : value
              .toFixed(fractionDigits)
              .replace(/0+$/u, "")
              .replace(/\.$/u, "");

const formatTraceTimelineOffset = (offsetMs: number): string => {
    if (offsetMs === 0) {
        return "0ms";
    }
    if (offsetMs < 1000) {
        return `${formatDecimal(offsetMs, 3)}ms`;
    }

    const totalSeconds = offsetMs / 1000;
    if (totalSeconds < 60) {
        return `${formatDecimal(totalSeconds, 2)}s`;
    }

    const wholeSeconds = Math.round(totalSeconds);
    const hours = Math.floor(wholeSeconds / 3600);
    const minutes = Math.floor((wholeSeconds % 3600) / 60);
    const seconds = wholeSeconds % 60;
    return [
        hours > 0 ? `${hours}h` : undefined,
        minutes > 0 ? `${minutes}m` : undefined,
        seconds > 0 ? `${seconds}s` : undefined,
    ]
        .filter((part): part is string => part !== undefined)
        .join(" ");
};

export const getTraceTimelineSpanLayout = (
    offsetMs: number,
    durationMs: number,
    traceDurationMs: number,
): TraceTimelineSpanLayout => {
    const normalizedTraceDuration = normalizeDuration(traceDurationMs);
    if (normalizedTraceDuration === 0) {
        return { leftPx: 0, widthPx: MINIMUM_BAR_WIDTH_PX };
    }

    return {
        leftPx:
            (normalizeDuration(offsetMs) / normalizedTraceDuration) *
            TRACE_TIMELINE_SCALE_WIDTH_PX,
        widthPx: Math.max(
            (normalizeDuration(durationMs) / normalizedTraceDuration) *
                TRACE_TIMELINE_SCALE_WIDTH_PX,
            MINIMUM_BAR_WIDTH_PX,
        ),
    };
};

export const buildTraceTimelineScale = (
    durationMs: number | undefined,
): TraceTimelineScale => {
    const normalizedDuration = normalizeDuration(durationMs);
    if (normalizedDuration === 0) {
        return {
            ticks: [{ label: "0ms", leftPx: 0, offsetMs: 0 }],
            widthPx: TRACE_TIMELINE_SCALE_WIDTH_PX,
        };
    }

    const tickIntervalMs = getNiceTickInterval(normalizedDuration);
    const tickCount = Math.floor(normalizedDuration / tickIntervalMs) + 1;
    const ticks = Array.from({ length: tickCount }, (_item, index) => {
        const offsetMs = index * tickIntervalMs;
        return {
            label: formatTraceTimelineOffset(offsetMs),
            leftPx:
                (offsetMs / normalizedDuration) *
                TRACE_TIMELINE_SCALE_WIDTH_PX,
            offsetMs,
        };
    });

    return {
        ticks,
        widthPx: TRACE_TIMELINE_SCALE_WIDTH_PX,
    };
};
