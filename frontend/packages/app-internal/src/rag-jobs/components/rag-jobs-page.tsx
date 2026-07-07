import type {
    ColumnDef,
    PaginationState,
    SortingState,
} from "@tanstack/react-table";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import { Skeleton } from "@va/shared/components/ui/skeleton";
import { RefreshCw } from "lucide-react";
import { type JSX, useEffect, useMemo, useState } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { DataTable } from "../../components/data-table";
import { DATA_TABLE_DEFAULT_PAGE_SIZE } from "../../components/data-table-constants";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError } from "../../components/page-state";
import { formatTableTimestamp } from "../../lib/date-format";
import { formatLocaleNumber } from "../../lib/number-format";
import { fetchRagBuildJob, fetchRagBuildJobs } from "../lib/api";
import type {
    RagBuildJobDetail,
    RagBuildJobDocumentChange,
    RagBuildJobSummary,
} from "../types";

const statusOptions = [
    { label: "All statuses", value: "all" },
    { label: "Running", value: "running" },
    { label: "Completed", value: "completed" },
    { label: "Failed", value: "failed" },
    { label: "Skipped", value: "skipped" },
    { label: "Cancelled", value: "cancelled" },
] as const;

const triggerOptions = [
    { label: "All triggers", value: "all" },
    { label: "Manual", value: "manual" },
    { label: "Scheduled", value: "scheduled" },
    { label: "CLI", value: "cli" },
] as const;

const statusLabel = (status: string): string => {
    switch (status) {
        case "running": {
            return "Running";
        }
        case "completed": {
            return "Completed";
        }
        case "failed":
        case "error": {
            return "Failed";
        }
        case "skipped": {
            return "Skipped";
        }
        case "cancelled": {
            return "Cancelled";
        }
        default: {
            return status;
        }
    }
};

const triggerLabel = (trigger: string): string => {
    switch (trigger) {
        case "manual": {
            return "Manual";
        }
        case "scheduled": {
            return "Scheduled";
        }
        case "cli": {
            return "CLI";
        }
        default: {
            return trigger;
        }
    }
};

const changeTypeLabel = (changeType: string): string => {
    switch (changeType) {
        case "new": {
            return "New";
        }
        case "changed": {
            return "Changed";
        }
        case "deleted": {
            return "Deleted";
        }
        default: {
            return changeType;
        }
    }
};

const documentTypeLabel = (documentType: string): string =>
    documentType
        .split("_")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");

const statusVariant = (
    status: string,
): "default" | "secondary" | "destructive" | "outline" => {
    switch (status) {
        case "running": {
            return "default";
        }
        case "completed": {
            return "secondary";
        }
        case "failed":
        case "error": {
            return "destructive";
        }
        default: {
            return "outline";
        }
    }
};

const changeVariant = (
    changeType: string,
): "default" | "secondary" | "destructive" | "outline" => {
    switch (changeType) {
        case "new": {
            return "default";
        }
        case "changed": {
            return "secondary";
        }
        case "deleted": {
            return "destructive";
        }
        default: {
            return "outline";
        }
    }
};

const formatCount = (value: number): string => formatLocaleNumber(value);

const formatDuration = (durationMs: number | undefined): string => {
    if (durationMs === undefined) {
        return "-";
    }
    if (durationMs < 1000) {
        return `${formatLocaleNumber(Math.round(durationMs))}ms`;
    }
    if (durationMs < 60_000) {
        return `${formatLocaleNumber(durationMs / 1000, {
            maximumFractionDigits: 1,
            minimumFractionDigits: 1,
        })}s`;
    }
    return `${formatLocaleNumber(durationMs / 60_000, {
        maximumFractionDigits: 1,
        minimumFractionDigits: 1,
    })}m`;
};

const skeletonLine = (className: string): JSX.Element => (
    <Skeleton className={className} />
);

const buildColumns = (): ColumnDef<RagBuildJobSummary>[] => [
    {
        id: "started_at",
        accessorKey: "startedAt",
        header: "Started",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-24") },
        cell: ({ row }): JSX.Element => (
            <div className="text-xs tabular-nums">
                {formatTableTimestamp(row.original.startedAt)}
            </div>
        ),
    },
    {
        id: "status",
        accessorKey: "status",
        header: "Status",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-20") },
        cell: ({ row }): JSX.Element => (
            <Badge variant={statusVariant(row.original.status)}>
                {statusLabel(row.original.status)}
            </Badge>
        ),
    },
    {
        id: "trigger",
        accessorKey: "trigger",
        header: "Trigger",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-20") },
        cell: ({ row }): JSX.Element => (
            <div className="text-sm">{triggerLabel(row.original.trigger)}</div>
        ),
    },
    {
        id: "duration_ms",
        accessorKey: "durationMs",
        header: "Duration",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-16") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatDuration(row.original.durationMs)}
            </div>
        ),
    },
    {
        id: "changed_count",
        accessorKey: "totalChanged",
        header: "Changed",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-14") },
        cell: ({ row }): JSX.Element => (
            <div className="text-right text-xs tabular-nums">
                {formatCount(row.original.totalChanged)}
            </div>
        ),
    },
    {
        id: "new_count",
        accessorKey: "totalNew",
        header: "New",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-14") },
        cell: ({ row }): JSX.Element => (
            <div className="text-right text-xs tabular-nums">
                {formatCount(row.original.totalNew)}
            </div>
        ),
    },
    {
        id: "deleted_count",
        accessorKey: "totalDeleted",
        header: "Deleted",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-14") },
        cell: ({ row }): JSX.Element => (
            <div className="text-right text-xs tabular-nums">
                {formatCount(row.original.totalDeleted)}
            </div>
        ),
    },
    {
        id: "force_rebuild",
        accessorKey: "forceRebuild",
        header: "Mode",
        meta: { skeleton: skeletonLine("h-5 w-20") },
        cell: ({ row }): JSX.Element => (
            <Badge variant="outline">
                {row.original.forceRebuild ? "Rebuild" : "Incremental"}
            </Badge>
        ),
    },
];

const ChangeList = ({
    changes,
}: {
    changes: RagBuildJobDocumentChange[];
}): JSX.Element => {
    if (changes.length === 0) {
        return (
            <div className="text-muted-foreground rounded-md border p-3 text-sm">
                No new, changed, or deleted documents were recorded for this
                job.
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-2">
            {changes.map((change) => {
                const previousTitleChanged =
                    change.previousTitle !== undefined &&
                    change.previousTitle !== change.title;
                const previousUrlChanged =
                    change.previousUrl !== undefined &&
                    change.previousUrl !== change.url;
                const showPrevious =
                    change.changeType === "changed" &&
                    (previousTitleChanged || previousUrlChanged);

                return (
                    <div
                        className="rounded-md border p-3"
                        key={change.id}
                    >
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                            <Badge variant={changeVariant(change.changeType)}>
                                {changeTypeLabel(change.changeType)}
                            </Badge>
                            <Badge variant="outline">
                                {documentTypeLabel(change.documentType)} #
                                {change.sourceId}
                            </Badge>
                            <span className="text-muted-foreground text-xs">
                                {change.sourceName}
                            </span>
                        </div>
                        <div className="text-sm font-medium break-words">
                            {change.title}
                        </div>
                        <a
                            className="text-primary text-xs break-all hover:underline"
                            href={change.url}
                            rel="noreferrer"
                            target="_blank"
                        >
                            {change.url}
                        </a>
                        {showPrevious && (
                            <div className="text-muted-foreground mt-2 border-t pt-2 text-xs">
                                <div className="font-medium">Previous</div>
                                {previousTitleChanged && (
                                    <div className="break-words">
                                        {change.previousTitle}
                                    </div>
                                )}
                                {previousUrlChanged && (
                                    <div className="break-all">
                                        {change.previousUrl}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
};

const JobDetail = ({
    detail,
    loading,
    error,
    onRetry,
}: {
    detail: RagBuildJobDetail | undefined;
    loading: boolean;
    error: string | undefined;
    onRetry: () => void;
}): JSX.Element => {
    if (loading) {
        return (
            <Card className="flex h-full min-h-0 flex-col overflow-hidden">
                <CardHeader>
                    <CardTitle>Job detail</CardTitle>
                </CardHeader>
                <CardContent className="min-h-0 flex-1 space-y-3 overflow-auto">
                    <Skeleton className="h-5 w-40" />
                    <Skeleton className="h-24 w-full" />
                    <Skeleton className="h-40 w-full" />
                </CardContent>
            </Card>
        );
    }

    if (error !== undefined) {
        return (
            <Card className="flex h-full min-h-0 flex-col overflow-hidden">
                <CardHeader>
                    <CardTitle>Job detail</CardTitle>
                </CardHeader>
                <CardContent>
                    <InlineError
                        message={error}
                        onRetry={onRetry}
                    />
                </CardContent>
            </Card>
        );
    }

    if (detail === undefined) {
        return (
            <Card className="flex h-full min-h-0 flex-col overflow-hidden">
                <CardHeader>
                    <CardTitle>Job detail</CardTitle>
                </CardHeader>
                <CardContent className="text-muted-foreground text-sm">
                    Select a KB builder job to inspect its steps and document
                    changes.
                </CardContent>
            </Card>
        );
    }

    return (
        <Card className="flex h-full min-h-0 flex-col overflow-hidden">
            <CardHeader className="shrink-0 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle>Job detail</CardTitle>
                    <Badge variant={statusVariant(detail.status)}>
                        {statusLabel(detail.status)}
                    </Badge>
                </div>
                <div className="text-muted-foreground grid gap-1 text-xs">
                    <div>Started: {formatTableTimestamp(detail.startedAt)}</div>
                    <div>
                        Finished: {formatTableTimestamp(detail.finishedAt)}
                    </div>
                    <div>Duration: {formatDuration(detail.durationMs)}</div>
                    <div>Trigger: {triggerLabel(detail.trigger)}</div>
                    <div>Started by: {detail.startedBy?.email ?? "-"}</div>
                    {detail.errorMessage !== undefined && (
                        <div className="text-destructive break-words">
                            Error: {detail.errorMessage}
                        </div>
                    )}
                </div>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 space-y-4 overflow-auto">
                <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Totals</h3>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                        <div className="rounded-md border p-2">
                            <div className="text-muted-foreground text-xs">
                                Changed
                            </div>
                            <div className="font-semibold tabular-nums">
                                {formatCount(detail.totalChanged)}
                            </div>
                        </div>
                        <div className="rounded-md border p-2">
                            <div className="text-muted-foreground text-xs">
                                New
                            </div>
                            <div className="font-semibold tabular-nums">
                                {formatCount(detail.totalNew)}
                            </div>
                        </div>
                        <div className="rounded-md border p-2">
                            <div className="text-muted-foreground text-xs">
                                Deleted
                            </div>
                            <div className="font-semibold tabular-nums">
                                {formatCount(detail.totalDeleted)}
                            </div>
                        </div>
                        <div className="rounded-md border p-2">
                            <div className="text-muted-foreground text-xs">
                                Unchanged
                            </div>
                            <div className="font-semibold tabular-nums">
                                {formatCount(detail.totalUnchanged)}
                            </div>
                        </div>
                    </div>
                </section>

                <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Steps</h3>
                    <div className="space-y-2">
                        {detail.steps.map((step) => (
                            <div
                                className="flex items-center justify-between gap-3 rounded-md border p-2"
                                key={step.stepKey}
                            >
                                <div className="min-w-0">
                                    <div className="truncate text-sm font-medium">
                                        {step.label}
                                    </div>
                                    <div className="text-muted-foreground text-xs">
                                        {formatTableTimestamp(step.startedAt)} →{" "}
                                        {formatTableTimestamp(step.finishedAt)}
                                    </div>
                                </div>
                                <Badge variant={statusVariant(step.status)}>
                                    {statusLabel(step.status)}
                                </Badge>
                            </div>
                        ))}
                    </div>
                </section>

                <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Source stats</h3>
                    <div className="space-y-2">
                        {detail.sourceStats.map((stat) => (
                            <div
                                className="rounded-md border p-2 text-sm"
                                key={`${stat.sourceName}-${stat.documentType}`}
                            >
                                <div className="font-medium">
                                    {stat.sourceName}
                                </div>
                                <div className="text-muted-foreground text-xs">
                                    {documentTypeLabel(stat.documentType)} ·
                                    source{" "}
                                    {formatCount(stat.sourceDocumentCount)} ·
                                    existing{" "}
                                    {formatCount(stat.existingDocumentCount)}
                                </div>
                                <div className="mt-2 grid grid-cols-4 gap-2 text-xs tabular-nums">
                                    <span>
                                        New {formatCount(stat.newCount)}
                                    </span>
                                    <span>
                                        Changed {formatCount(stat.changedCount)}
                                    </span>
                                    <span>
                                        Deleted {formatCount(stat.deletedCount)}
                                    </span>
                                    <span>
                                        Same {formatCount(stat.unchangedCount)}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>

                <section className="space-y-2">
                    <h3 className="text-sm font-semibold">
                        Document changes (
                        {formatCount(detail.documentChanges.length)})
                    </h3>
                    <ChangeList changes={detail.documentChanges} />
                </section>
            </CardContent>
        </Card>
    );
};

export const RagJobsPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const [jobs, setJobs] = useState<RagBuildJobSummary[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | undefined>();
    const [refreshCount, setRefreshCount] = useState(0);
    const [selectedJobId, setSelectedJobId] = useState<string | undefined>();
    const [detail, setDetail] = useState<RagBuildJobDetail | undefined>();
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | undefined>();
    const [statusFilter, setStatusFilter] = useState("all");
    const [triggerFilter, setTriggerFilter] = useState("all");
    const [pagination, setPagination] = useState<PaginationState>({
        pageIndex: 0,
        pageSize: DATA_TABLE_DEFAULT_PAGE_SIZE,
    });
    const [sorting, setSorting] = useState<SortingState>([
        { desc: true, id: "started_at" },
    ]);

    useEffect((): (() => void) => {
        let active = true;
        const load = async (): Promise<void> => {
            const [sort] = sorting;
            setLoading(true);
            setError(undefined);
            try {
                const page = await fetchRagBuildJobs(api, {
                    limit: pagination.pageSize,
                    offset: pagination.pageIndex * pagination.pageSize,
                    sortBy: sort?.id ?? "started_at",
                    descending: sort?.desc ?? true,
                    status: statusFilter,
                    trigger: triggerFilter,
                });
                if (active) {
                    setJobs(page.items);
                    setTotal(page.total);
                }
            } catch (fetchError: unknown) {
                if (active) {
                    setError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : "Failed to load KB builder jobs",
                    );
                }
            } finally {
                if (active) {
                    setLoading(false);
                }
            }
        };
        void load();
        return (): void => {
            active = false;
        };
    }, [
        api,
        pagination.pageIndex,
        pagination.pageSize,
        refreshCount,
        sorting,
        statusFilter,
        triggerFilter,
    ]);

    const effectiveSelectedJobId = useMemo(() => {
        if (
            selectedJobId !== undefined &&
            jobs.some((job) => job.id === selectedJobId)
        ) {
            return selectedJobId;
        }
        return jobs[0]?.id;
    }, [jobs, selectedJobId]);

    useEffect((): (() => void) => {
        let active = true;
        const load = async (): Promise<void> => {
            if (effectiveSelectedJobId === undefined) {
                setDetail(undefined);
                setDetailError(undefined);
                setDetailLoading(false);
                return;
            }

            setDetailLoading(true);
            setDetailError(undefined);
            try {
                const jobDetail = await fetchRagBuildJob(
                    api,
                    effectiveSelectedJobId,
                );
                if (active) {
                    setDetail(jobDetail);
                }
            } catch (fetchError: unknown) {
                if (active) {
                    setDetailError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : "Failed to load KB builder job detail",
                    );
                }
            } finally {
                if (active) {
                    setDetailLoading(false);
                }
            }
        };
        void load();
        return (): void => {
            active = false;
        };
    }, [api, effectiveSelectedJobId, refreshCount]);

    const columns = useMemo(() => buildColumns(), []);
    const pageCount = Math.max(1, Math.ceil(total / pagination.pageSize));
    const selectedStatusLabel =
        statusOptions.find((option) => option.value === statusFilter)?.label ??
        "All statuses";
    const selectedTriggerLabel =
        triggerOptions.find((option) => option.value === triggerFilter)
            ?.label ?? "All triggers";

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="KB Builder Jobs">
                <PageHeaderGroup>
                    <Select
                        onValueChange={(value) => {
                            if (value === null) {
                                return;
                            }
                            setStatusFilter(value);
                            setPagination((current) => ({
                                ...current,
                                pageIndex: 0,
                            }));
                        }}
                        value={statusFilter}
                    >
                        <SelectTrigger
                            aria-label="Status"
                            className="w-[150px]"
                        >
                            <SelectValue>{selectedStatusLabel}</SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {statusOptions.map((option) => (
                                    <SelectItem
                                        key={option.value}
                                        value={option.value}
                                    >
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </PageHeaderGroup>
                <PageHeaderGroup>
                    <Select
                        onValueChange={(value) => {
                            if (value === null) {
                                return;
                            }
                            setTriggerFilter(value);
                            setPagination((current) => ({
                                ...current,
                                pageIndex: 0,
                            }));
                        }}
                        value={triggerFilter}
                    >
                        <SelectTrigger
                            aria-label="Trigger"
                            className="w-[150px]"
                        >
                            <SelectValue>{selectedTriggerLabel}</SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {triggerOptions.map((option) => (
                                    <SelectItem
                                        key={option.value}
                                        value={option.value}
                                    >
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </PageHeaderGroup>
                <Button
                    onClick={() => {
                        setRefreshCount((current) => current + 1);
                    }}
                    type="button"
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
                <div className="flex min-h-0 flex-col">
                    {error !== undefined && (
                        <InlineError
                            message={error}
                            onRetry={() => {
                                setRefreshCount((current) => current + 1);
                            }}
                        />
                    )}
                    <DataTable
                        columns={columns}
                        data={jobs}
                        emptyMessage="No KB builder jobs matched."
                        isLoading={loading}
                        isRowSelected={(row) =>
                            row.id === effectiveSelectedJobId
                        }
                        manualPagination
                        manualSorting
                        onPaginationChange={setPagination}
                        onRowClick={(row) => {
                            setSelectedJobId(row.id);
                        }}
                        onSortingChange={setSorting}
                        pageCount={pageCount}
                        pagination={pagination}
                        rowCount={total}
                        sorting={sorting}
                    />
                </div>
                <div className="flex min-h-0 flex-col">
                    <JobDetail
                        detail={detail}
                        error={detailError}
                        loading={detailLoading}
                        onRetry={() => {
                            setRefreshCount((current) => current + 1);
                        }}
                    />
                </div>
            </PageSection>
        </PageShell>
    );
};
