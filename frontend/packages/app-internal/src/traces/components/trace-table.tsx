import type {
    ColumnDef,
    OnChangeFn,
    PaginationState,
    SortingState,
} from "@tanstack/react-table";
import { Badge } from "@va/shared/components/ui/badge";
import { Skeleton } from "@va/shared/components/ui/skeleton";
import type { JSX } from "react";

import { DataTable } from "@/components/data-table";

import { formatLocaleNumber } from "../../lib/number-format";
import {
    formatDurationMs,
    formatPlatform,
    formatTimestamp,
} from "../lib/trace-utils";
import type { TraceSummary } from "../types";

interface TraceTableProps {
    traces: TraceSummary[];
    rowCount: number;
    selectedTraceId: string | undefined;
    isLoading: boolean;
    onSelect: (trace: TraceSummary) => void;
    pagination: PaginationState;
    pageCount: number;
    onPaginationChange: OnChangeFn<PaginationState>;
    showPlatformColumn?: boolean;
}

const formatTraceId = (traceId: string): string => traceId;

const skeletonLine = (className: string): JSX.Element => (
    <Skeleton className={className} />
);

const SpansHeader = (): JSX.Element => <div className="text-right">Spans</div>;

const DurationHeader = (): JSX.Element => (
    <div className="text-right">Duration</div>
);

const buildTraceColumns = (
    showPlatformColumn: boolean,
): ColumnDef<TraceSummary>[] => {
    const columns: ColumnDef<TraceSummary>[] = [
        {
            id: "started_at",
            header: "Time",
            enableSorting: false,
            meta: {
                skeleton: skeletonLine("h-[18px] w-24"),
            },
            cell: ({ row }) => formatTimestamp(row.original.started_at),
        },
        {
            id: "trace_id",
            header: "Trace",
            enableSorting: false,
            meta: {
                skeleton: skeletonLine("h-[18px] w-24"),
            },
            cell: ({ row }) => (
                <span title={row.original.trace_id}>
                    {formatTraceId(row.original.trace_id)}
                </span>
            ),
        },
        {
            id: "root_span_name",
            header: "Root",
            enableSorting: false,
            meta: {
                skeleton: skeletonLine("h-[18px] w-32"),
            },
            cell: ({ row }) => row.original.root_span_name ?? "-",
        },
        {
            id: "span_count",
            header: SpansHeader,
            enableSorting: false,
            meta: {
                skeleton: (
                    <div className="flex justify-end">
                        {skeletonLine("h-5 w-10")}
                    </div>
                ),
            },
            cell: ({ row }) => (
                <div className="text-right tabular-nums">
                    {formatLocaleNumber(row.original.span_count)}
                </div>
            ),
        },
        {
            id: "duration_ms",
            header: DurationHeader,
            enableSorting: false,
            meta: {
                skeleton: (
                    <div className="flex justify-end">
                        {skeletonLine("h-5 w-14")}
                    </div>
                ),
            },
            cell: ({ row }) => (
                <div className="text-right tabular-nums">
                    {formatDurationMs(row.original.duration_ms)}
                </div>
            ),
        },
        {
            id: "status",
            header: "Status",
            enableSorting: false,
            meta: {
                skeleton: skeletonLine("h-[22px] w-16 rounded-full"),
            },
            cell: ({ row }) => (
                <Badge
                    variant={
                        row.original.is_error ? "destructive" : "secondary"
                    }
                >
                    {row.original.is_error ? "Error" : "OK"}
                </Badge>
            ),
        },
    ];

    if (showPlatformColumn) {
        columns.splice(3, 0, {
            id: "platform",
            header: "Platform",
            enableSorting: false,
            meta: {
                skeleton: skeletonLine("h-[18px] w-16"),
            },
            cell: ({ row }) => formatPlatform(row.original.is_public),
        });
    }

    return columns;
};

const emptySorting: SortingState = [];
const noopSortingChange: OnChangeFn<SortingState> = (updater) => {
    void updater;
};

export const TraceTable = ({
    traces,
    rowCount,
    selectedTraceId,
    isLoading,
    onSelect,
    pagination,
    pageCount,
    onPaginationChange,
    showPlatformColumn = true,
}: TraceTableProps): JSX.Element => (
    <DataTable
        columns={buildTraceColumns(showPlatformColumn)}
        data={traces}
        emptyMessage="No traces available yet."
        isLoading={isLoading}
        isRowSelected={(row) => row.trace_id === selectedTraceId}
        manualPagination
        manualSorting
        onPaginationChange={onPaginationChange}
        onRowClick={(trace) => {
            onSelect(trace);
        }}
        onSortingChange={noopSortingChange}
        pageCount={pageCount}
        pagination={pagination}
        rowCount={rowCount}
        sorting={emptySorting}
    />
);
