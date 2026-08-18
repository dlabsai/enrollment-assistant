import type {
    TraceOutcome,
    TraceOverviewItem,
    TraceSpan,
} from "../types";

export const getTraceSpanOutcome = (
    span: TraceSpan | undefined,
    overviewItem: TraceOverviewItem | undefined,
): TraceOutcome | null =>
    overviewItem?.outcome ??
    (span?.status_code === "ERROR" ? "error" : null);

export const getAggregateFailedResultCount = (
    item: TraceOverviewItem | undefined,
): number | undefined =>
    item?.type === "evaluation" || item?.type === "evaluation_case"
        ? item.failed_result_count
        : undefined;

const traceOutcomeSurfaceClass = (
    outcome: TraceOutcome | null | undefined,
): string => {
    if (outcome === "fail") {
        return "bg-destructive/10";
    }
    if (outcome === "error") {
        return "bg-amber-500/10";
    }
    return "";
};

export const traceOutcomeRailClass = (
    outcome: TraceOutcome | null | undefined,
): string => {
    if (outcome === "fail") {
        return "!border-l-destructive border-l-2";
    }
    if (outcome === "error") {
        return "!border-l-amber-600 border-l-2 dark:!border-l-amber-400";
    }
    return "";
};

export const traceOutcomeRowClass = (
    outcome: TraceOutcome | null | undefined,
): string =>
    [traceOutcomeRailClass(outcome), traceOutcomeSurfaceClass(outcome)]
        .filter(Boolean)
        .join(" ");

export const traceOutcomeBarClass = (
    outcome: TraceOutcome | null | undefined,
    fallback: string,
): string => {
    if (outcome === "fail") {
        return "bg-destructive";
    }
    if (outcome === "error") {
        return "bg-amber-600 dark:bg-amber-400";
    }
    if (outcome === "pass") {
        return "bg-emerald-600 dark:bg-emerald-400";
    }
    return fallback;
};

export const traceTimelineBarClass = (
    outcome: TraceOutcome | null | undefined,
): string => traceOutcomeBarClass(outcome, "bg-muted-foreground");
