import type { ColumnDef, PaginationState } from "@tanstack/react-table";
import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Progress,
    ProgressLabel,
    ProgressValue,
} from "@va/shared/components/ui/progress";
import { ArrowLeft, Info, RotateCcw } from "lucide-react";
import { type JSX, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { DataTable } from "../../components/data-table";
import { HelpDialog } from "../../components/help-dialog";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection } from "../../components/page-shell";
import {
    InlineError,
    LoadingState,
    PageError,
} from "../../components/page-state";
import { formatTableTimestamp } from "../../lib/date-format";
import { formatLocaleNumber as number } from "../../lib/number-format";
import { useComplianceData } from "../hooks/use-compliance-data";
import {
    decisionLabel,
    formatScreeningDateRange,
    formatScreeningPeriod,
    screeningLabel,
    screeningStatusVariant,
} from "../lib/presentation";
import type {
    FlagsPage,
    FlagSummary,
    ScreeningDetail,
} from "../types";
import { FlagReview } from "./flag-review";

interface Selection {
    flag?: string;
    page: number;
    pageSize: number;
}
interface Props extends Selection {
    screeningId: string;
    onBack: () => void;
    onSelection: (selection: Selection, replace?: boolean) => void;
}

const flagStatusVariant = (
    state: FlagSummary["state"],
): "default" | "outline" | "secondary" => {
    if (state === "needs_review") {
        return "default";
    }
    return state === "confirmed" ? "secondary" : "outline";
};

const flagColumns: ColumnDef<FlagSummary>[] = [
    {
        accessorKey: "title",
        header: "Flag",
        cell: ({ row }) => (
            <div
                className="max-w-[520px] min-w-0 truncate font-medium"
                title={row.original.title}
            >
                {row.original.title}
            </div>
        ),
    },
    {
        accessorKey: "chat",
        header: "Chat",
        cell: ({ row }) => (
            <div
                className="max-w-[280px] min-w-0 truncate"
                title={row.original.chat}
            >
                {row.original.chat}
            </div>
        ),
    },
    {
        accessorKey: "message_at",
        header: "Message",
        cell: ({ row }) => (
            <div className="text-muted-foreground text-xs whitespace-nowrap">
                {formatTableTimestamp(row.original.message_at)}
            </div>
        ),
    },
    {
        accessorKey: "state",
        header: "Decision",
        cell: ({ row }) => (
            <Badge variant={flagStatusVariant(row.original.state)}>
                {decisionLabel(row.original.state)}
            </Badge>
        ),
    },
];

export const ScreeningWorkspace = ({
    screeningId,
    flag,
    page,
    pageSize,
    onBack,
    onSelection,
}: Props): JSX.Element => {
    const api = useAuthenticatedApi();
    const [instructionsOpen, setInstructionsOpen] = useState(false);
    const [retrying, setRetrying] = useState(false);
    const loadScreening = useCallback(
        async (signal: AbortSignal) =>
            api.get<ScreeningDetail>(`/compliance/screenings/${screeningId}`, {
                signal,
            }),
        [api, screeningId],
    );
    const {
        data,
        error: screeningError,
        refresh: handleScreeningRefresh,
    } = useComplianceData({
        load: loadScreening,
        errorMessage: "Could not load this screening.",
    });
    const loadFlags = useCallback(
        async (signal: AbortSignal) => ({
            ...(await api.get<FlagsPage>(
                `/compliance/screenings/${screeningId}/flags?offset=${page * pageSize}&limit=${pageSize}`,
                { signal },
            )),
            pagination: { pageIndex: page, pageSize },
        }),
        [api, screeningId, page, pageSize],
    );
    const flags = useComplianceData({
        load: loadFlags,
        errorMessage: "Could not load flags.",
        retainPreviousData: true,
    });
    const nextFlagEnabled =
        flag === undefined && data?.pending === 0 && data.needs_review > 0;
    const loadNextFlag = useCallback(
        async (signal: AbortSignal) => {
            if (!nextFlagEnabled) {
                return { items: [], total: 0 };
            }
            return api.get<FlagsPage>(
                `/compliance/screenings/${screeningId}/flags?offset=0&limit=1`,
                { signal },
            );
        },
        [api, screeningId, nextFlagEnabled],
    );
    const nextFlag = useComplianceData({
        load: loadNextFlag,
        enabled: nextFlagEnabled,
        errorMessage: "Could not load the next flag.",
    });
    const handleFlagsRefresh = flags.refresh;
    useEffect(() => {
        if (
            flag !== undefined ||
            flags.loading ||
            flags.error !== undefined ||
            !flags.data
        ) {
            return;
        }
        const lastPage = Math.max(
            0,
            Math.ceil(flags.data.total / pageSize) - 1,
        );
        if (page > lastPage) {
            onSelection({ page: lastPage, pageSize }, true);
        }
    }, [
        flag,
        flags.data,
        flags.loading,
        flags.error,
        page,
        pageSize,
        onSelection,
    ]);
    const refresh = (): void => {
        handleScreeningRefresh();
        handleFlagsRefresh();
        nextFlag.refresh();
    };
    const retry = async (): Promise<void> => {
        setRetrying(true);
        try {
            const result = await api.post<{
                queued: number;
                conversations: number;
            }>(`/compliance/screenings/${screeningId}/retry`, {});
            const chatLabel = result.conversations === 1 ? "chat" : "chats";
            const messageLabel =
                result.queued === 1 ? "message" : "messages";
            toast.success(
                result.conversations > 0
                    ? `Retrying ${number(result.conversations)} ${chatLabel} covering ${number(result.queued)} selected assistant ${messageLabel}.`
                    : "No failed chats to retry.",
            );
            refresh();
        } catch (error) {
            toast.error(
                error instanceof Error
                    ? error.message
                    : "Could not retry. Please try again.",
            );
        } finally {
            setRetrying(false);
        }
    };
    const rows = flags.data?.items ?? [];
    const firstPending = nextFlag.data?.items.find(
        (candidate) => candidate.state === "needs_review",
    );
    const changePagination = (
        updater:
            PaginationState | ((previous: PaginationState) => PaginationState),
    ): void => {
        const previous = { pageIndex: page, pageSize };
        const updated =
            typeof updater === "function" ? updater(previous) : updater;
        onSelection({
            page: updated.pageSize === pageSize ? updated.pageIndex : 0,
            pageSize: updated.pageSize,
        });
    };
    const failure =
        screeningError === undefined ? undefined : (
            <InlineError
                message={screeningError}
                onRetry={handleScreeningRefresh}
            />
        );
    if (data === undefined) {
        return (
            <>
                <PageHeader
                    title="Screening"
                    titleAddon={
                        <Button
                            onClick={
                                flag === undefined
                                    ? onBack
                                    : (): void => {
                                          onSelection({ page, pageSize });
                                      }
                            }
                            variant="outline"
                        >
                            <ArrowLeft data-icon="inline-start" />
                            {flag === undefined
                                ? "Back to screenings"
                                : "Back to screening"}
                        </Button>
                    }
                />
                <PageSection className="flex min-h-0 flex-1 flex-col">
                    {screeningError === undefined ? (
                        <LoadingState />
                    ) : (
                        <PageError
                            message={screeningError}
                            onRetry={handleScreeningRefresh}
                        />
                    )}
                </PageSection>
            </>
        );
    }
    if (flag !== undefined) {
        return (
            <FlagReview
                flagId={flag}
                loadingRows={flags.loading}
                notice={failure}
                onBack={() => {
                    onSelection({ page, pageSize });
                }}
                onSaved={refresh}
                onSelect={(flagId) => {
                    onSelection({
                        flag: flagId,
                        page,
                        pageSize,
                    });
                }}
                rows={rows}
                screeningId={screeningId}
            />
        );
    }
    const pagination = flags.data?.pagination ?? { pageIndex: page, pageSize };
    const progressLabel = `${number(data.screened_conversations)} of ${number(data.conversations)} chat${data.conversations === 1 ? "" : "s"}`;
    const progressValue =
        data.conversations === 0
            ? 0
            : Math.round(
                  (data.screened_conversations / data.conversations) * 100,
              );
    const errorSummary = `${number(data.error_conversations)} Chat${data.error_conversations === 1 ? "" : "s"} could not be screened.`;
    const hasRetriableFailures = data.failures.some(
        (failed) => failed.retryable,
    );
    return (
        <>
            <PageHeader
                title="Screening"
                titleAddon={
                    <PageHeaderGroup>
                        <Button
                            onClick={onBack}
                            variant="outline"
                        >
                            <ArrowLeft data-icon="inline-start" />
                            Back to screenings
                        </Button>
                        <span
                            className="text-sm font-medium"
                            title={formatScreeningPeriod(data)}
                        >
                            {formatScreeningDateRange(data)}
                        </span>
                        <Badge
                            role="status"
                            variant={screeningStatusVariant(data)}
                        >
                            {screeningLabel(data)}
                        </Badge>
                    </PageHeaderGroup>
                }
            >
                {data.pending === 0 && data.needs_review > 0 && (
                    <Button
                        disabled={
                            nextFlag.loading || firstPending === undefined
                        }
                        onClick={() => {
                            if (firstPending) {
                                onSelection({
                                    flag: firstPending.id,
                                    page: 0,
                                    pageSize,
                                });
                            }
                        }}
                    >
                        Review next
                    </Button>
                )}
                <Button
                    onClick={() => {
                        setInstructionsOpen(true);
                    }}
                    variant="outline"
                >
                    <Info data-icon="inline-start" />
                    Instructions
                </Button>
            </PageHeader>
            <PageSection className="flex min-h-0 flex-1 flex-col gap-4">
                {failure}
                {data.admission_error !== null && (
                    <Alert variant="destructive">
                        <AlertDescription>{data.admission_error}</AlertDescription>
                    </Alert>
                )}
                <HelpDialog
                    onOpenChange={setInstructionsOpen}
                    open={instructionsOpen}
                    title="Instructions"
                >
                    <section
                        aria-label="Instructions used"
                        className="flex flex-col gap-3 text-sm"
                    >
                        <div className="flex flex-col gap-1">
                            <h3 className="font-semibold">
                                Version {data.instructions.number}
                            </h3>
                            <p className="text-muted-foreground">
                                Saved{" "}
                                {formatTableTimestamp(
                                    data.instructions.created_at,
                                )}{" "}
                                by {data.instructions.author}
                            </p>
                        </div>
                        <p className="break-words whitespace-pre-wrap">
                            {data.instructions.content}
                        </p>
                    </section>
                </HelpDialog>
                {data.pending > 0 ? (
                    <section aria-label="Screening progress">
                        <Progress value={progressValue}>
                            <ProgressLabel>{progressLabel}</ProgressLabel>
                            <ProgressValue />
                        </Progress>
                    </section>
                ) : (
                    <>
                        {data.errors > 0 && (
                            <Alert>
                                <AlertDescription>
                                    <div className="flex flex-col gap-2">
                                        <span>{errorSummary}</span>
                                        <ul
                                            aria-label="Chats that could not be screened"
                                            className="max-h-64 list-disc space-y-1 overflow-y-auto pl-5"
                                        >
                                            {data.failures.map((failed) => (
                                                <li
                                                    key={`${failed.chat_id}:${failed.reason}`}
                                                >
                                                    <span className="font-medium">
                                                        {failed.chat}
                                                    </span>
                                                    : {failed.reason}
                                                    {failed.assistant_messages > 1 &&
                                                        ` (${number(failed.assistant_messages)} selected assistant messages)`}
                                                </li>
                                            ))}
                                        </ul>
                                        {hasRetriableFailures && (
                                            <div>
                                                <Button
                                                    disabled={retrying}
                                                    onClick={() => {
                                                        void retry();
                                                    }}
                                                    variant="outline"
                                                >
                                                    <RotateCcw data-icon="inline-start" />
                                                    Retry
                                                </Button>
                                            </div>
                                        )}
                                    </div>
                                </AlertDescription>
                            </Alert>
                        )}
                        {data.deleted > 0 && (
                            <Alert>
                                <AlertDescription>
                                    {number(data.deleted)} assistant message
                                    {data.deleted === 1 ? " was" : "s were"} deleted,
                                    along with their flags.
                                </AlertDescription>
                            </Alert>
                        )}
                        {flags.error !== undefined && (
                            <InlineError
                                message={flags.error}
                                onRetry={handleFlagsRefresh}
                            />
                        )}
                        <div
                            aria-busy={flags.loading}
                            className="flex min-h-0 flex-1 flex-col"
                            inert={flags.loading}
                        >
                            <DataTable
                                columns={flagColumns}
                                data={rows}
                                emptyMessage="No flags found. AI screening does not guarantee compliance."
                                getRowActionLabel={(row) =>
                                    `Review flag: ${row.title}`
                                }
                                getRowId={(row) => row.id}
                                isLoading={
                                    flags.loading && flags.data === undefined
                                }
                                onPaginationChange={changePagination}
                                onRowClick={(row) => {
                                    onSelection({
                                        flag: row.id,
                                        page,
                                        pageSize,
                                    });
                                }}
                                pageCount={Math.ceil(
                                    (flags.data?.total ?? 0) /
                                        pagination.pageSize,
                                )}
                                pagination={pagination}
                                rowCount={flags.data?.total ?? 0}
                                showPagination={
                                    (flags.data?.total ?? 0) >
                                        pagination.pageSize ||
                                    pagination.pageIndex > 0
                                }
                                tableClassName="min-w-[44rem] tabular-nums"
                                wrapCellText
                            />
                        </div>
                    </>
                )}
            </PageSection>
        </>
    );
};
