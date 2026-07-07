import type {
    ColumnDef,
    OnChangeFn,
    PaginationState,
    SortingState,
} from "@tanstack/react-table";
import { Input } from "@va/shared/components/ui/input";
import type { JSX } from "react";

import { DataTable } from "../../components/data-table";
import {
    formatEvalAudience,
    formatOptionalNumber,
    formatPercentValue,
    formatTimestamp,
} from "../lib/report-utils";
import type { EvalReportSummary } from "../types";

interface EvalsReportsListProps {
    loading: boolean;
    onPaginationChange: OnChangeFn<PaginationState>;
    onSearchChange: (value: string) => void;
    onSelectReport: (reportId: string) => void;
    onSortingChange: OnChangeFn<SortingState>;
    pageCount: number;
    pagination: PaginationState;
    reports: EvalReportSummary[];
    rowCount: number;
    searchInputValue: string;
    selectedReportId?: string;
    sorting: SortingState;
}

const reportColumns: ColumnDef<EvalReportSummary>[] = [
    {
        id: "title",
        accessorKey: "title",
        header: "Name",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="font-medium break-words">
                {row.original.title}
            </span>
        ),
    },
    {
        id: "generated_at",
        accessorFn: (report) => Date.parse(report.generatedAt),
        header: "Generated",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {formatTimestamp(row.original.generatedAt)}
            </span>
        ),
    },
    {
        id: "audience",
        accessorFn: (report) => formatEvalAudience(report.isInternal),
        header: "Audience",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {formatEvalAudience(row.original.isInternal)}
            </span>
        ),
    },
    {
        id: "suite",
        accessorKey: "suite",
        header: "Suite",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {row.original.suite}
            </span>
        ),
    },
    {
        id: "case_count",
        accessorKey: "caseCount",
        header: () => <div className="text-right">Cases</div>,
        enableSorting: true,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatOptionalNumber(row.original.caseCount)}
            </div>
        ),
    },
    {
        id: "run_count",
        accessorKey: "runCount",
        header: () => <div className="text-right">Runs</div>,
        enableSorting: true,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatOptionalNumber(row.original.runCount)}
            </div>
        ),
    },
    {
        id: "repeats",
        accessorKey: "repeats",
        header: () => <div className="text-right">Repeats</div>,
        enableSorting: true,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatOptionalNumber(row.original.repeats)}
            </div>
        ),
    },
    {
        id: "concurrency",
        accessorKey: "concurrency",
        header: () => <div className="text-right">Concurrency</div>,
        enableSorting: true,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatOptionalNumber(row.original.concurrency)}
            </div>
        ),
    },
    {
        id: "pass_threshold",
        accessorKey: "passThreshold",
        header: () => <div className="text-right">Threshold</div>,
        enableSorting: true,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatPercentValue(row.original.passThreshold)}
            </div>
        ),
    },
    {
        id: "status",
        accessorKey: "status",
        header: "Status",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {row.original.status.replaceAll("_", " ")}
            </span>
        ),
    },
];

export const EvalsReportsList = ({
    loading,
    onPaginationChange,
    onSearchChange,
    onSelectReport,
    onSortingChange,
    pageCount,
    pagination,
    reports,
    rowCount,
    searchInputValue,
    selectedReportId,
    sorting,
}: EvalsReportsListProps): JSX.Element => (
    <section className="flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-hidden">
        <Input
            onChange={(event) => {
                onSearchChange(event.target.value);
            }}
            placeholder="Search..."
            value={searchInputValue}
        />
        <DataTable
            columns={reportColumns}
            data={reports}
            emptyMessage="No eval reports match the current filters."
            isLoading={loading}
            isRowSelected={(report) => selectedReportId === report.id}
            manualPagination
            manualSorting
            onPaginationChange={onPaginationChange}
            onRowClick={(report) => {
                onSelectReport(report.id);
            }}
            onSortingChange={onSortingChange}
            pageCount={pageCount}
            pagination={pagination}
            rowCount={rowCount}
            sorting={sorting}
            tableClassName="min-w-[1120px]"
            wrapCellText
        />
    </section>
);
