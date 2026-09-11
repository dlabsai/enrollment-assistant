import {
    Outlet,
    useNavigate,
    useParams,
    useSearch,
} from "@tanstack/react-router";
import type { ColumnDef, PaginationState } from "@tanstack/react-table";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import { ArrowLeft, BookOpenText } from "lucide-react";
import { type JSX, useCallback, useState } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { DataTable } from "../../components/data-table";
import { getDefaultDataTablePageSize } from "../../components/data-table-constants";
import { PageHeader } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError } from "../../components/page-state";
import { formatTableTimestamp } from "../../lib/date-format";
import { formatLocaleNumber } from "../../lib/number-format";
import { useComplianceData } from "../hooks/use-compliance-data";
import {
    formatScreeningDateRange,
    screeningLabel,
    screeningStatusVariant,
    serializeComplianceSearch,
} from "../lib/presentation";
import type { ScreeningsPage, ScreeningSummary } from "../types";
import { InstructionsPanel } from "./instructions-panel";
import { NewScreening } from "./new-screening";
import { ScreeningWorkspace } from "./screening-workspace";

const screeningColumns: ColumnDef<ScreeningSummary>[] = [
    {
        id: "period",
        header: "Period",
        cell: ({ row }) => (
            <div
                className="whitespace-nowrap"
                title={formatScreeningDateRange(row.original)}
            >
                {formatScreeningDateRange(row.original)}
            </div>
        ),
    },
    {
        id: "status",
        header: "Status",
        cell: ({ row }) => (
            <Badge variant={screeningStatusVariant(row.original)}>
                {screeningLabel(row.original)}
            </Badge>
        ),
    },
    {
        accessorKey: "findings",
        header: "Flags",
        cell: ({ row }) => formatLocaleNumber(row.original.findings),
    },
    {
        id: "reviewed",
        header: "Reviewed",
        cell: ({ row }) =>
            row.original.findings === 0
                ? "—"
                : `${formatLocaleNumber(row.original.findings - row.original.needs_review)} of ${formatLocaleNumber(row.original.findings)}`,
    },
];

const PreviousScreenings = ({
    onOpen,
}: {
    onOpen: (id: string) => void;
}): JSX.Element => {
    const api = useAuthenticatedApi();
    const [pagination, setPagination] = useState<PaginationState>(() => ({
        pageIndex: 0,
        pageSize: getDefaultDataTablePageSize(),
    }));
    const load = useCallback(
        async (signal: AbortSignal) => ({
            ...(await api.get<ScreeningsPage>(
                `/compliance/screenings?offset=${pagination.pageIndex * pagination.pageSize}&limit=${pagination.pageSize}`,
                { signal },
            )),
            pagination,
        }),
        [api, pagination],
    );
    const {
        data,
        loading,
        error,
        refresh: handleRefresh,
    } = useComplianceData({
        load,
        errorMessage: "Could not load previous screenings.",
        retainPreviousData: true,
    });
    const failure =
        error === undefined ? undefined : (
            <InlineError
                message={error}
                onRetry={handleRefresh}
            />
        );
    const displayedPagination = data?.pagination ?? pagination;
    return (
        <section
            aria-label="Previous screenings"
            className="flex min-h-0 flex-1 flex-col gap-3"
        >
            {failure}
            <div
                aria-busy={loading}
                className="flex min-h-0 flex-1 flex-col"
                inert={loading}
            >
                <DataTable
                    columns={screeningColumns}
                    data={data?.items ?? []}
                    emptyMessage="No previous screenings."
                    getRowActionLabel={(row) =>
                        `Open screening for ${formatScreeningDateRange(row)}, started ${formatTableTimestamp(row.created_at)}`
                    }
                    getRowId={(row) => row.id}
                    isLoading={loading && data === undefined}
                    onPaginationChange={setPagination}
                    onRowClick={(row) => {
                        onOpen(row.id);
                    }}
                    pageCount={Math.ceil(
                        (data?.total ?? 0) / displayedPagination.pageSize,
                    )}
                    pagination={displayedPagination}
                    rowCount={data?.total ?? 0}
                    tableClassName="min-w-[36rem] tabular-nums"
                    wrapCellText
                />
            </div>
        </section>
    );
};

export const CompliancePage = (): JSX.Element => <Outlet />;

export const ComplianceHomePage = (): JSX.Element => {
    const navigate = useNavigate({ from: "/compliance/" });
    const openScreening = useCallback(
        (screeningId: string): void => {
            void navigate({
                to: "/compliance/screenings/$screeningId",
                params: { screeningId },
            });
        },
        [navigate],
    );
    return (
        <PageShell className="min-h-0 overflow-hidden tabular-nums">
            <PageHeader title="Screenings">
                <NewScreening onStarted={openScreening} />
                <Button
                    onClick={() => {
                        void navigate({ to: "/compliance/instructions" });
                    }}
                    variant="outline"
                >
                    <BookOpenText data-icon="inline-start" />
                    Instructions
                </Button>
            </PageHeader>
            <PageSection className="flex min-h-0 w-full flex-1 flex-col gap-4">
                <PreviousScreenings onOpen={openScreening} />
            </PageSection>
        </PageShell>
    );
};

export const ComplianceInstructionsPage = (): JSX.Element => {
    const navigate = useNavigate({ from: "/compliance/instructions" });
    return (
        <PageShell className="tabular-nums [scrollbar-gutter:stable]">
            <PageHeader
                title="Screening instructions"
                titleAddon={
                    <Button
                        onClick={() => {
                            void navigate({ to: "/compliance" });
                        }}
                        variant="outline"
                    >
                        <ArrowLeft data-icon="inline-start" />
                        Back to screenings
                    </Button>
                }
            />
            <PageSection className="w-full max-w-3xl">
                <InstructionsPanel />
            </PageSection>
        </PageShell>
    );
};

const ComplianceScreeningWorkspacePage = ({
    screeningId,
    flag,
    page,
    pageSize,
}: {
    screeningId: string;
    flag?: string;
    page: number;
    pageSize: number;
}): JSX.Element => {
    const navigate = useNavigate();
    return (
        <PageShell className="min-h-0 overflow-hidden tabular-nums">
            <ScreeningWorkspace
                flag={flag}
                key={screeningId}
                onBack={() => {
                    void navigate({ to: "/compliance" });
                }}
                onSelection={(selection, replace = false) => {
                    const search = serializeComplianceSearch(
                        selection.page,
                        selection.pageSize,
                    );
                    if (selection.flag === undefined) {
                        void navigate({
                            params: { screeningId },
                            replace,
                            search,
                            to: "/compliance/screenings/$screeningId",
                        });
                        return;
                    }
                    void navigate({
                        params: {
                            screeningId,
                            flagId: selection.flag,
                        },
                        replace,
                        search,
                        to: "/compliance/screenings/$screeningId/flags/$flagId",
                    });
                }}
                page={page}
                pageSize={pageSize}
                screeningId={screeningId}
            />
        </PageShell>
    );
};

export const ComplianceScreeningPage = (): JSX.Element => {
    const { screeningId } = useParams({
        from: "/compliance/screenings/$screeningId",
    });
    const search = useSearch({
        from: "/compliance/screenings/$screeningId",
    });
    return (
        <ComplianceScreeningWorkspacePage
            page={(search.page ?? 1) - 1}
            pageSize={search.pageSize ?? getDefaultDataTablePageSize()}
            screeningId={screeningId}
        />
    );
};

export const ComplianceFlagPage = (): JSX.Element => {
    const { flagId, screeningId } = useParams({
        from: "/compliance/screenings/$screeningId/flags/$flagId",
    });
    const search = useSearch({
        from: "/compliance/screenings/$screeningId/flags/$flagId",
    });
    return (
        <ComplianceScreeningWorkspacePage
            flag={flagId}
            page={(search.page ?? 1) - 1}
            pageSize={search.pageSize ?? getDefaultDataTablePageSize()}
            screeningId={screeningId}
        />
    );
};
