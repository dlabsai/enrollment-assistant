import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import { RefreshCw } from "lucide-react";
import { type JSX, useCallback, useMemo } from "react";

import { PageHeader } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { formatLocaleNumber } from "../../lib/number-format";
import { useTraceDetail } from "../hooks/use-trace-detail";
import {
    formatDurationMs,
    formatPlatform,
    formatTimestamp,
} from "../lib/trace-utils";
import { TraceDetailPanel } from "./trace-detail-panel";

const formatTraceId = (traceId: string): string => traceId;

type TraceDetailView = "span" | "summary";

interface TraceDetailContentProps {
    routePath: "/traces/$traceId" | "/eval-traces/$traceId";
    source: "runtime" | "evals";
    traceId: string;
}

const TraceDetailContent = ({
    routePath,
    source,
    traceId,
}: TraceDetailContentProps): JSX.Element => {
    const search = useSearch({ strict: false });
    const navigate = useNavigate();

    const { detail, loading, error, refresh } = useTraceDetail(traceId, source);

    const detailTitle = `Trace ${formatTraceId(traceId)}`;
    const detailDescription = useMemo(() => {
        if (!detail) {
            return "Trace details";
        }
        return (
            <span className="inline-flex flex-wrap items-center gap-2">
                <Badge
                    variant={
                        detail.is_public === true ? "secondary" : "outline"
                    }
                >
                    {formatPlatform(detail.is_public)}
                </Badge>
                <span>{formatTimestamp(detail.started_at)}</span>
                <span>{formatDurationMs(detail.duration_ms)}</span>
                <span>{formatLocaleNumber(detail.span_count)} spans</span>
            </span>
        );
    }, [detail]);

    const handleSpanChange = useCallback(
        (spanId: string | undefined): void => {
            void navigate({
                params: { traceId },
                search: (prev) => ({
                    span: spanId,
                    view:
                        prev.view === "span" || prev.view === "summary"
                            ? prev.view
                            : undefined,
                }),
                to: routePath,
            });
        },
        [navigate, routePath, traceId],
    );

    const handleSpanSync = useCallback(
        (spanId: string | undefined): void => {
            void navigate({
                params: { traceId },
                replace: true,
                search: (prev) => ({
                    span: spanId,
                    view:
                        prev.view === "span" || prev.view === "summary"
                            ? prev.view
                            : undefined,
                }),
                to: routePath,
            });
        },
        [navigate, routePath, traceId],
    );

    const handleViewChange = useCallback(
        (view: TraceDetailView): void => {
            void navigate({
                params: { traceId },
                search: (prev) => ({
                    span:
                        typeof prev.span === "string" && prev.span !== ""
                            ? prev.span
                            : undefined,
                    view,
                }),
                to: routePath,
            });
        },
        [navigate, routePath, traceId],
    );

    return (
        <PageShell
            className="overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title={detailTitle}>
                <Button
                    onClick={() => void refresh()}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection className="flex min-h-0 flex-1 flex-col gap-4">
                <div className="text-muted-foreground text-sm">
                    {detailDescription}
                </div>
                <div className="min-h-0 flex-1 overflow-hidden">
                    <TraceDetailPanel
                        detail={detail}
                        error={error}
                        loading={loading}
                        onSpanChange={handleSpanChange}
                        onSpanSync={handleSpanSync}
                        onViewChange={handleViewChange}
                        selectedSpanId={search.span}
                        view={
                            search.view === "span" || search.view === "summary"
                                ? (search.view as TraceDetailView)
                                : undefined
                        }
                    />
                </div>
            </PageSection>
        </PageShell>
    );
};

export const TraceDetailPage = (): JSX.Element => {
    const { traceId } = useParams({ from: "/traces/$traceId" });
    return (
        <TraceDetailContent
            routePath="/traces/$traceId"
            source="runtime"
            traceId={traceId}
        />
    );
};

export const EvalTraceDetailPage = (): JSX.Element => {
    const { traceId } = useParams({ from: "/eval-traces/$traceId" });
    return (
        <TraceDetailContent
            routePath="/eval-traces/$traceId"
            source="evals"
            traceId={traceId}
        />
    );
};
