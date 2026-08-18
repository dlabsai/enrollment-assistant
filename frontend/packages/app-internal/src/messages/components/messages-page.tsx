import type {
    ColumnDef,
    SortingState,
    VisibilityState,
} from "@tanstack/react-table";
import { DEFAULT_HIGHLIGHT_CLASS } from "@va/shared/components/highlighted-text";
import { Badge } from "@va/shared/components/ui/badge";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "@va/shared/components/ui/sheet";
import { Skeleton } from "@va/shared/components/ui/skeleton";
import { UNIVERSITY_NAME } from "@va/shared/config";
import { setDocumentTitle } from "@va/shared/lib/document-title";
import { type JSX, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
import { fetchChatDetail } from "../../chat/lib/api";
import type { ChatDetailResponse } from "../../chat/types";
import { ChatReviewSheetActions } from "../../chats/components/chat-review-sheet-actions";
import { ChatTurnTraceSheet } from "../../chats/components/chat-turn-trace-sheet";
import { ChatDetailContent } from "../../chats/components/chats-page";
import {
    useCopyChatTranscript,
    usePersistentChatSummary,
} from "../../chats/hooks/use-chat-review-controls";
import { fetchChatUsers } from "../../chats/lib/api";
import {
    buildOwnerGroupFilterOptions,
    buildUserFilterParams,
} from "../../chats/lib/user-filter-options";
import type { ChatUserOption } from "../../chats/types";
import { DataTable } from "../../components/data-table";
import { DataTableColumnVisibility } from "../../components/data-table-column-visibility";
import { getDefaultDataTablePageSize } from "../../components/data-table-constants";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError } from "../../components/page-state";
import { ReviewTableToolbar } from "../../components/review-table-toolbar";
import { formatTableTimestamp } from "../../lib/date-format";
import {
    formatLocaleNumber,
    formatUsdCost,
} from "../../lib/number-format";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import { fetchMessageListPage } from "../lib/api";
import type {
    MessageListPage as MessageListPageResponse,
    MessageListRow,
} from "../types";

const formatTimestamp = formatTableTimestamp;

const COLUMN_VISIBILITY_STORAGE_KEY = "messages-table-column-visibility";

const loadColumnVisibility = (): VisibilityState => {
    if (typeof window === "undefined") {
        return {};
    }

    try {
        const stored = window.localStorage.getItem(
            COLUMN_VISIBILITY_STORAGE_KEY,
        );
        if (stored === null) {
            return {};
        }
        const parsed: unknown = JSON.parse(stored);
        if (
            typeof parsed !== "object" ||
            parsed === null ||
            Array.isArray(parsed)
        ) {
            return {};
        }
        return Object.fromEntries(
            Object.entries(parsed).filter(([, value]) =>
                typeof value === "boolean"
            ),
        );
    } catch {
        return {};
    }
};

const formatCount = (value: number): string => formatLocaleNumber(value);

const formatOptionalCount = (value: number | undefined): string =>
    value === undefined ? "-" : formatCount(value);

type MessageRoleFilter = "assistant" | "user" | "all";

const MESSAGE_ROLE_OPTIONS: { label: string; value: MessageRoleFilter }[] = [
    { label: "All roles", value: "all" },
    { label: "User role", value: "user" },
    { label: "Assistant role", value: "assistant" },
];

const isMessageRoleFilter = (
    value: string | null,
): value is MessageRoleFilter =>
    MESSAGE_ROLE_OPTIONS.some((option) => option.value === value);

const formatDuration = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    if (value < 1000) {
        return `${formatLocaleNumber(value)}ms`;
    }
    return `${formatLocaleNumber(value / 1000, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
    })}s`;
};

const skeletonLine = (className: string): JSX.Element => (
    <Skeleton className={className} />
);

const openUrl = (url: string): void => {
    window.open(url, "_blank", "noopener,noreferrer");
};

const openChatInNewTab = (conversationId: string): void => {
    const base = `${window.location.origin}${window.location.pathname}`;
    openUrl(`${base}#/chats/${conversationId}`);
};

const buildColumns = (
    canViewResponseCost: boolean,
): ColumnDef<MessageListRow>[] => [
    {
        id: "content_length",
        accessorKey: "contentLength",
        header: "Length",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-20") },
        cell: ({ row }): JSX.Element => (
            <div className="tabular-nums">
                {formatCount(row.original.contentLength)} chars
            </div>
        ),
    },
    {
        id: "role",
        accessorKey: "role",
        header: "Role",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-20") },
        cell: ({ row }): JSX.Element => (
            <Badge
                variant={
                    row.original.role === "assistant" ? "default" : "outline"
                }
            >
                {row.original.role}
            </Badge>
        ),
    },
    {
        id: "message",
        header: "Message",
        meta: { skeleton: skeletonLine("h-10 w-96") },
        cell: ({ row }): JSX.Element => (
            <div className="line-clamp-2 max-w-[520px] min-w-0 text-sm break-words whitespace-normal">
                {row.original.contentPreview}
            </div>
        ),
    },
    {
        id: "conversation_title",
        accessorKey: "conversationTitle",
        header: "Chat",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-8 w-52") },
        cell: ({ row }): JSX.Element => (
            <div className="max-w-[260px] min-w-0">
                <div className="truncate text-sm font-semibold">
                    {row.original.conversationTitle ?? "Untitled chat"}
                </div>
                <div className="text-muted-foreground text-xs">
                    {row.original.isPublic ? "Public" : "Internal"}
                </div>
            </div>
        ),
    },
    {
        id: "conversation_user",
        header: "Chat user",
        meta: { skeleton: skeletonLine("h-8 w-44") },
        cell: ({ row }): JSX.Element => (
            <div className="max-w-[220px] min-w-0">
                <div className="truncate text-sm">
                    {row.original.conversationUserName ?? "-"}
                </div>
                {row.original.conversationUserEmail !== undefined && (
                    <div className="text-muted-foreground truncate text-xs">
                        {row.original.conversationUserEmail}
                    </div>
                )}
            </div>
        ),
    },
    {
        id: "generation_time_ms",
        accessorKey: "generationTimeMs",
        header: "Generation",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-20") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatDuration(row.original.generationTimeMs)}
            </div>
        ),
    },
    {
        id: "uncached_input_tokens",
        accessorKey: "uncachedInputTokens",
        header: "Uncached input",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-16") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatOptionalCount(row.original.uncachedInputTokens)}
            </div>
        ),
    },
    {
        id: "cache_read_input_tokens",
        accessorKey: "cacheReadInputTokens",
        header: "Cached input",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-16") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatOptionalCount(row.original.cacheReadInputTokens)}
            </div>
        ),
    },
    {
        id: "output_tokens",
        accessorKey: "outputTokens",
        header: "Output",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-16") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatOptionalCount(row.original.outputTokens)}
            </div>
        ),
    },
    ...(canViewResponseCost
        ? [
              {
                  id: "response_cost",
                  accessorKey: "responseCost",
                  header: "Cost",
                  enableSorting: true,
                  meta: { skeleton: skeletonLine("h-5 w-16") },
                  cell: ({
                      row,
                  }: {
                      row: { original: MessageListRow };
                  }): JSX.Element => (
                      <div className="text-muted-foreground text-xs tabular-nums">
                          {formatUsdCost(row.original.responseCost)}
                      </div>
                  ),
              },
          ]
        : []),
    {
        id: "tool_call_count",
        accessorKey: "toolCallCount",
        header: "Tools",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-14") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatCount(row.original.toolCallCount)}
            </div>
        ),
    },
    {
        id: "guardrail_failure_count",
        accessorKey: "guardrailFailureCount",
        header: "Guardrails failed",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-14") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatCount(row.original.guardrailFailureCount)}
            </div>
        ),
    },
    {
        id: "guardrails_blocked",
        accessorKey: "guardrailsBlocked",
        header: "Blocked",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-16") },
        cell: ({ row }): JSX.Element => (
            <Badge
                variant={
                    row.original.guardrailsBlocked ? "destructive" : "outline"
                }
            >
                {row.original.guardrailsBlocked ? "Yes" : "No"}
            </Badge>
        ),
    },
    {
        id: "created_at",
        accessorKey: "createdAt",
        header: "Created",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-3 w-24") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs">
                {formatTimestamp(row.original.createdAt)}
            </div>
        ),
    },
];

export const MessagesPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const { user } = useAuth();
    const canFilterUsers = user?.permissions.access_messages === true;
    const ownerGroupFilterOptions = useMemo(
        () => buildOwnerGroupFilterOptions(user),
        [user],
    );
    const canViewTrace = hasPermission(user, "chats_view_trace");
    const canViewDurationTooltip = hasPermission(user, "chat_duration_tooltip");
    const canViewResponseCost = hasPermission(user, "chat_view_response_cost");
    const canViewGuardrailsFailures = hasPermission(
        user,
        "chat_view_guardrails_failures",
    );
    const canViewSources = hasPermission(user, "chat_view_sources");
    const canViewTools = hasPermission(user, "chat_view_tools");

    const [searchInput, setSearchInput] = useState("");
    const [searchQuery, setSearchQuery] = useState("");
    const [role, setRole] = useState<MessageRoleFilter>("assistant");
    const [timeRange, setTimeRange] = useState<TimeRangeValue>("30d");
    const [customRange, setCustomRange] = useState<CustomTimeRange>({});
    const [selectedUser, setSelectedUser] = useState<
        ChatUserOption | undefined
    >();
    const [userSearchInput, setUserSearchInput] = useState("");
    const [userSearchQuery, setUserSearchQuery] = useState("");
    const [userOptions, setUserOptions] = useState<ChatUserOption[]>([]);
    const [userPopoverOpen, setUserPopoverOpen] = useState(false);
    const [userLoading, setUserLoading] = useState(false);
    const [pageIndex, setPageIndex] = useState(0);
    const [pageSize, setPageSize] = useState(getDefaultDataTablePageSize);
    const [sorting, setSorting] = useState<SortingState>([
        { id: "created_at", desc: true },
    ]);
    const [columnVisibility, setColumnVisibility] =
        useState<VisibilityState>(loadColumnVisibility);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | undefined>();
    const [page, setPage] = useState<MessageListPageResponse | undefined>();
    const [refreshToken, setRefreshToken] = useState(0);
    const [selectedMessage, setSelectedMessage] = useState<
        MessageListRow | undefined
    >();
    const [detail, setDetail] = useState<ChatDetailResponse | undefined>();
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | undefined>();
    const [tracePanelOpen, setTracePanelOpen] = useState(false);
    const [traceMessageId, setTraceMessageId] = useState<string | undefined>();
    const [showSummary, setShowSummary] = usePersistentChatSummary(
        "messages-chat-summary-open",
    );

    useEffect(() => {
        const timeout = setTimeout(() => {
            setSearchQuery(searchInput.trim());
            setPageIndex(0);
        }, 300);
        return (): void => {
            clearTimeout(timeout);
        };
    }, [searchInput]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            setUserSearchQuery(userSearchInput.trim());
        }, 300);
        return (): void => {
            clearTimeout(timeout);
        };
    }, [userSearchInput]);

    useEffect(() => {
        let isMounted = true;
        const loadUsers = async (): Promise<void> => {
            if (!userPopoverOpen || !canFilterUsers) {
                return;
            }
            setUserLoading(true);
            try {
                const response = await fetchChatUsers(api, {
                    search: userSearchQuery,
                    limit: 50,
                });
                if (isMounted) {
                    setUserOptions(response);
                }
            } catch {
                if (isMounted) {
                    setUserOptions([]);
                }
            } finally {
                if (isMounted) {
                    setUserLoading(false);
                }
            }
        };
        void loadUsers();
        return (): void => {
            isMounted = false;
        };
    }, [api, canFilterUsers, userPopoverOpen, userSearchQuery]);

    useEffect(() => {
        let isMounted = true;
        const load = async (): Promise<void> => {
            setLoading(true);
            setError(undefined);
            try {
                const userFilterParams = canFilterUsers
                    ? buildUserFilterParams(selectedUser)
                    : {};

                const response = await fetchMessageListPage(api, {
                    search: searchQuery,
                    userEmail: userFilterParams.userEmail,
                    userGroup: userFilterParams.userGroup,
                    role,
                    limit: pageSize,
                    offset: pageIndex * pageSize,
                    sortBy: sorting[0]?.id ?? "created_at",
                    descending: sorting[0]?.desc ?? true,
                    timeRange,
                    customRange,
                });
                if (isMounted) {
                    setPage(response);
                }
            } catch (error_) {
                if (isMounted) {
                    setError(
                        error_ instanceof Error
                            ? error_.message
                            : "Failed to load messages",
                    );
                }
            } finally {
                if (isMounted) {
                    setLoading(false);
                }
            }
        };
        void load();
        return (): void => {
            isMounted = false;
        };
    }, [
        api,
        canFilterUsers,
        customRange,
        pageIndex,
        pageSize,
        refreshToken,
        role,
        searchQuery,
        selectedUser,
        sorting,
        timeRange,
    ]);

    useEffect(() => {
        const baseTitle = `${UNIVERSITY_NAME} Enrollment Assistant`;
        setDocumentTitle(
            selectedMessage
                ? `Message · Messages · ${baseTitle}`
                : `Messages · ${baseTitle}`,
        );
    }, [selectedMessage]);

    useEffect((): (() => void) => {
        if (selectedMessage === undefined) {
            return (): void => undefined;
        }

        let active = true;
        const loadDetail = async (): Promise<void> => {
            setDetailLoading(true);
            setDetailError(undefined);
            try {
                const response = await fetchChatDetail(
                    api,
                    selectedMessage.conversationId,
                    {
                        source: "messages",
                        targetMessageId: selectedMessage.id,
                    },
                );
                if (active) {
                    setDetail(response);
                }
            } catch (error_) {
                if (active) {
                    setDetailError(
                        error_ instanceof Error
                            ? error_.message
                            : "Failed to load chat",
                    );
                }
            } finally {
                if (active) {
                    setDetailLoading(false);
                }
            }
        };
        void loadDetail();

        return (): void => {
            active = false;
        };
    }, [api, selectedMessage]);

    useEffect(() => {
        try {
            window.localStorage.setItem(
                COLUMN_VISIBILITY_STORAGE_KEY,
                JSON.stringify(columnVisibility),
            );
        } catch {
            // Keep the in-memory preference when browser storage is unavailable.
        }
    }, [columnVisibility]);

    const columns = useMemo(
        () => buildColumns(canViewResponseCost),
        [canViewResponseCost],
    );
    const tableData = page?.items ?? [];
    const pageCount = Math.max(1, Math.ceil((page?.total ?? 0) / pageSize));
    const userOptionsWithOwnerGroups = useMemo(
        () => [...ownerGroupFilterOptions, ...userOptions],
        [ownerGroupFilterOptions, userOptions],
    );
    const selectedUserLabel =
        selectedUser?.name ?? selectedUser?.email ?? "All users";
    const selectedRoleLabel =
        MESSAGE_ROLE_OPTIONS.find((option) => option.value === role)?.label ??
        "Assistant role";
    const detailTitle =
        selectedMessage?.conversationTitle ?? detail?.title ?? "Chat";
    const highlightQuery = searchInput.trim();
    const selectedIndex = selectedMessage
        ? tableData.findIndex((row) => row.id === selectedMessage.id)
        : -1;
    const canGoPrev = selectedIndex > 0;
    const canGoNext =
        selectedIndex >= 0 && selectedIndex < tableData.length - 1;
    const openMessage = (row: MessageListRow): void => {
        setSelectedMessage(row);
        setDetail(undefined);
        setDetailError(undefined);
        setDetailLoading(true);
    };
    const openTracePanel = (messageId: string): void => {
        setTraceMessageId(messageId);
        setTracePanelOpen(true);
    };
    const copyTranscript = useCopyChatTranscript(detail);
    const detailContent = (
        <ChatDetailContent
            canViewDurationTooltip={canViewDurationTooltip}
            canViewGuardrailsFailures={canViewGuardrailsFailures}
            canViewResponseCost={canViewResponseCost}
            canViewSources={canViewSources}
            canViewTools={canViewTools}
            canViewTrace={canViewTrace}
            detail={detail}
            error={detailError}
            focusMessageId={selectedMessage?.id}
            highlightPhrase={false}
            highlightQuery={highlightQuery}
            loading={detailLoading}
            onDetailChange={setDetail}
            onFeedbackChange={(): void => undefined}
            onOpenTrace={openTracePanel}
            showSummary={showSummary}
            source="messages"
        />
    );

    return (
        <PageShell className="overflow-hidden">
            <PageHeader title="Messages">
                <ReviewTableToolbar
                    canFilterUsers={canFilterUsers}
                    customRange={customRange}
                    extraFilters={
                        <PageHeaderGroup>
                            <Select
                                onValueChange={(value) => {
                                    if (isMessageRoleFilter(value)) {
                                        setRole(value);
                                        setPageIndex(0);
                                    }
                                }}
                                value={role}
                            >
                                <SelectTrigger
                                    aria-label="Role"
                                    className="w-[140px]"
                                >
                                    <SelectValue>
                                        {selectedRoleLabel}
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        {MESSAGE_ROLE_OPTIONS.map((option) => (
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
                            <DataTableColumnVisibility
                                columnVisibility={columnVisibility}
                                columns={columns}
                                onColumnVisibilityChange={setColumnVisibility}
                            />
                        </PageHeaderGroup>
                    }
                    onClear={() => {
                        setSearchInput("");
                        setSearchQuery("");
                        setSelectedUser(undefined);
                        setRole("assistant");
                        setTimeRange("30d");
                        setCustomRange({});
                        setPageIndex(0);
                        setSorting([{ id: "created_at", desc: true }]);
                    }}
                    onCustomRangeChange={(value) => {
                        setCustomRange(value);
                        setPageIndex(0);
                    }}
                    onRefresh={() => {
                        setRefreshToken((value) => value + 1);
                    }}
                    onSearchInputChange={setSearchInput}
                    onSelectedUserChange={(option) => {
                        setSelectedUser(option);
                        setUserPopoverOpen(false);
                        setPageIndex(0);
                    }}
                    onTimeRangeChange={(value) => {
                        setTimeRange(value);
                        setPageIndex(0);
                    }}
                    onUserPopoverOpenChange={setUserPopoverOpen}
                    onUserSearchInputChange={setUserSearchInput}
                    searchInput={searchInput}
                    selectedUserLabel={selectedUserLabel}
                    timeRange={timeRange}
                    userLoading={userLoading}
                    userOptions={userOptionsWithOwnerGroups}
                    userPopoverOpen={userPopoverOpen}
                    userSearchInput={userSearchInput}
                />
            </PageHeader>
            <PageSection className="flex min-h-0 flex-1 flex-col gap-4">
                {error !== undefined && <InlineError message={error} />}
                <DataTable
                    columnVisibility={columnVisibility}
                    columns={columns}
                    data={tableData}
                    emptyMessage="No messages found."
                    isLoading={loading}
                    isRowSelected={(row) => row.id === selectedMessage?.id}
                    manualPagination
                    manualSorting
                    onPaginationChange={(updater) => {
                        const next =
                            typeof updater === "function"
                                ? updater({ pageIndex, pageSize })
                                : updater;
                        setPageIndex(
                            next.pageSize === pageSize ? next.pageIndex : 0,
                        );
                        setPageSize(next.pageSize);
                    }}
                    onRowClick={(row) => {
                        openMessage(row);
                    }}
                    onSortingChange={(updater) => {
                        setSorting(updater);
                        setPageIndex(0);
                    }}
                    pageCount={pageCount}
                    pagination={{ pageIndex, pageSize }}
                    rowCount={page?.total ?? 0}
                    sorting={sorting}
                />
            </PageSection>
            <Sheet
                onOpenChange={(open) => {
                    if (!open) {
                        setSelectedMessage(undefined);
                        setDetail(undefined);
                        setDetailError(undefined);
                        setTracePanelOpen(false);
                        setTraceMessageId(undefined);
                    }
                }}
                open={selectedMessage !== undefined}
            >
                <SheetContent
                    className="flex !w-[min(100vw,860px)] !max-w-[min(100vw,860px)] flex-col gap-4 p-0"
                    initialFocus={false}
                >
                    <SheetHeader className="border-b px-4 py-4">
                        <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                                <SheetTitle>{detailTitle}</SheetTitle>
                                {selectedMessage !== undefined && (
                                    <SheetDescription>
                                        <span className="flex flex-wrap items-center gap-2">
                                            <Badge variant="outline">
                                                {selectedMessage.role}
                                            </Badge>
                                            <span>
                                                {formatCount(
                                                    selectedMessage.contentLength,
                                                )}{" "}
                                                chars
                                            </span>
                                            <span>
                                                {formatTimestamp(
                                                    selectedMessage.createdAt,
                                                )}
                                            </span>
                                        </span>
                                    </SheetDescription>
                                )}
                            </div>
                            {selectedMessage !== undefined && (
                                <ChatReviewSheetActions
                                    canGoNext={canGoNext}
                                    canGoPrev={canGoPrev}
                                    copyDisabled={detail === undefined}
                                    nextLabel="Next message"
                                    onCopyTranscript={() => {
                                        void copyTranscript();
                                    }}
                                    onGoNext={() => {
                                        if (!canGoNext) {
                                            return;
                                        }
                                        openMessage(
                                            tableData[selectedIndex + 1],
                                        );
                                    }}
                                    onGoPrev={() => {
                                        if (!canGoPrev) {
                                            return;
                                        }
                                        openMessage(
                                            tableData[selectedIndex - 1],
                                        );
                                    }}
                                    onOpenChat={() => {
                                        openChatInNewTab(
                                            selectedMessage.conversationId,
                                        );
                                    }}
                                    onShowSummaryChange={setShowSummary}
                                    openChatTooltip="Open chat in new tab"
                                    previousLabel="Previous message"
                                    showSummary={showSummary}
                                    summaryToggleId="messages-summary-toggle"
                                />
                            )}
                        </div>
                    </SheetHeader>
                    <div className="min-h-0 flex-1 overflow-hidden">
                        {detailContent}
                    </div>

                    {highlightQuery !== "" && (
                        <div className="border-t px-4 py-3">
                            <div className="text-muted-foreground text-xs">
                                Highlighting matches for{" "}
                                <span className={DEFAULT_HIGHLIGHT_CLASS}>
                                    {highlightQuery}
                                </span>
                            </div>
                        </div>
                    )}
                </SheetContent>
            </Sheet>

            <ChatTurnTraceSheet
                messageId={traceMessageId}
                onOpenChange={(open) => {
                    setTracePanelOpen(open);
                    if (!open) {
                        setTraceMessageId(undefined);
                    }
                }}
                open={tracePanelOpen}
                source="chats_trace"
            />
        </PageShell>
    );
};
