import { Info } from "lucide-react";
import { type JSX, memo, useCallback, useMemo, useState } from "react";

import { LoadingState } from "@/components/page-state";

import {
    type TraceCollapseControls,
    useTraceCollapse,
} from "../hooks/use-trace-collapse";
import type { TraceLayoutScope } from "../lib/trace-layout";
import { hydrateSpansWithProjectedOutput } from "../lib/trace-projection-utils";
import { getResolvedTraceTiming } from "../lib/trace-utils";
import type { TraceDetail } from "../types";
import { TraceTurnSummary } from "./trace-turn-summary";

interface TraceTurnDebugViewProps {
    detail: TraceDetail | undefined;
    loading: boolean;
    error: string | undefined;
    selectedSpanId?: string;
    onSpanChange?: (spanId: string) => void;
    collapseControls?: TraceCollapseControls;
    layoutScope?: TraceLayoutScope;
}

export const TraceTurnDebugView = memo(
    ({
        detail,
        loading,
        error,
        selectedSpanId: externalSelectedSpanId,
        onSpanChange,
        collapseControls: externalCollapseControls,
        layoutScope = "page",
    }: TraceTurnDebugViewProps): JSX.Element => {
        const spans = useMemo(
            () => hydrateSpansWithProjectedOutput(detail),
            [detail],
        );
        const selectedSpanIdDefault = spans[0]?.span_id;
        const [localSelectedSpanId, setLocalSelectedSpanId] = useState<
            string | undefined
        >(externalSelectedSpanId ?? selectedSpanIdDefault);
        const spanIds = useMemo(
            () => new Set(spans.map((span) => span.span_id)),
            [spans],
        );
        const localCollapseControls = useTraceCollapse();
        const collapseControls =
            externalCollapseControls ?? localCollapseControls;

        let resolvedSelectedSpanId = selectedSpanIdDefault;
        if (
            externalSelectedSpanId !== undefined &&
            spanIds.has(externalSelectedSpanId)
        ) {
            resolvedSelectedSpanId = externalSelectedSpanId;
        } else if (
            localSelectedSpanId !== undefined &&
            spanIds.has(localSelectedSpanId)
        ) {
            resolvedSelectedSpanId = localSelectedSpanId;
        }

        const { end: traceEnd, start: traceStart } = useMemo(
            () => getResolvedTraceTiming(spans),
            [spans],
        );

        const handleSpanSelect = useCallback(
            (spanId: string): void => {
                if (externalSelectedSpanId === undefined) {
                    setLocalSelectedSpanId(spanId);
                }
                onSpanChange?.(spanId);
            },
            [externalSelectedSpanId, onSpanChange],
        );

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
            content = (
                <TraceTurnSummary
                    collapseControls={collapseControls}
                    layoutScope={layoutScope}
                    onSelectSpan={handleSpanSelect}
                    overview={detail.overview}
                    selectedSpanId={resolvedSelectedSpanId}
                    spans={spans}
                    traceEnd={traceEnd}
                    traceStart={traceStart}
                />
            );
        }

        return <div className="h-full min-h-0 overflow-hidden">{content}</div>;
    },
);
TraceTurnDebugView.displayName = "TraceTurnDebugView";
