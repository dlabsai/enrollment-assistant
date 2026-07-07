import { useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
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
import { FileSpreadsheet, ThumbsDown, ThumbsUp } from "lucide-react";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
import { fetchChatDetail } from "../../chat/lib/api";
import { getResponseLinkBaseUrl } from "../../chat/lib/response-link";
import type { ChatDetailResponse, Rating } from "../../chat/types";
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
import { getDefaultDataTablePageSize } from "../../components/data-table-constants";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError } from "../../components/page-state";
import { ReviewTableToolbar } from "../../components/review-table-toolbar";
import { formatTableTimestamp } from "../../lib/date-format";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import { fetchFeedbackExport, fetchFeedbackListPage } from "../lib/api";
import {
    downloadFeedbackExcel,
    getFeedbackExportTimeSettings,
} from "../lib/export";
import type {
    FeedbackListPage as FeedbackListPageResponse,
    FeedbackListRow,
} from "../types";

const formatTimestamp = formatTableTimestamp;

const skeletonLine = (className: string): JSX.Element => (
    <Skeleton className={className} />
);

type FeedbackRatingFilter = Rating | "all";

const FEEDBACK_RATING_OPTIONS: {
    label: string;
    value: FeedbackRatingFilter;
}[] = [
    { label: "All ratings", value: "all" },
    { label: "Thumbs up", value: "thumbs_up" },
    { label: "Thumbs down", value: "thumbs_down" },
];

const buildColumns = (): ColumnDef<FeedbackListRow>[] => [
    {
        id: "rating",
        accessorKey: "rating",
        header: "Feedback",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-28") },
        cell: ({ row }): JSX.Element => (
            <div className="space-y-1">
                <div
                    className={
                        row.original.rating === "thumbs_down"
                            ? "text-destructive inline-flex items-center gap-1"
                            : "inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400"
                    }
                >
                    {row.original.rating === "thumbs_down" ? (
                        <ThumbsDown className="size-4" />
                    ) : (
                        <ThumbsUp className="size-4" />
                    )}
                    <span className="text-xs font-medium">
                        {row.original.rating === "thumbs_down" ? "Down" : "Up"}
                    </span>
                </div>
                {row.original.text !== undefined &&
                    row.original.text !== "" && (
                        <div className="text-muted-foreground max-w-[320px] text-xs break-words whitespace-normal">
                            {row.original.text}
                        </div>
                    )}
            </div>
        ),
    },
    {
        id: "message",
        header: "Assistant message",
        meta: { skeleton: skeletonLine("h-10 w-72") },
        cell: ({ row }): JSX.Element => (
            <div className="line-clamp-2 max-w-[360px] min-w-0 text-sm">
                {row.original.messagePreview}
            </div>
        ),
    },
    {
        id: "chat",
        accessorKey: "conversationTitle",
        header: "Chat",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-8 w-52") },
        cell: ({ row }): JSX.Element => (
            <div className="max-w-[260px] min-w-0 truncate text-sm font-semibold">
                {row.original.conversationTitle ?? "Untitled chat"}
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
        id: "feedback_user",
        header: "Feedback by",
        meta: { skeleton: skeletonLine("h-8 w-44") },
        cell: ({ row }): JSX.Element => (
            <div className="max-w-[220px] min-w-0">
                <div className="truncate text-sm">
                    {row.original.feedbackUserName}
                </div>
                <div className="text-muted-foreground truncate text-xs">
                    {row.original.feedbackUserEmail}
                </div>
            </div>
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

export const FeedbackPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const { user } = useAuth();
    const search = useSearch({ from: "/feedback" });
    const navigate = useNavigate();
    const canFilterUsers =
        hasPermission(user, "chats_view_users") ||
        hasPermission(user, "chats_view_admins") ||
        hasPermission(user, "chats_view_devs");
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
    const [rating, setRating] = useState<FeedbackRatingFilter>("all");
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
    const [loading, setLoading] = useState(true);
    const [exporting, setExporting] = useState(false);
    const [error, setError] = useState<string | undefined>();
    const [page, setPage] = useState<FeedbackListPageResponse | undefined>();
    const [refreshToken, setRefreshToken] = useState(0);
    const [selectedFeedback, setSelectedFeedback] = useState<
        FeedbackListRow | undefined
    >();
    const [sheetOpen, setSheetOpen] = useState(false);
    const [detail, setDetail] = useState<ChatDetailResponse | undefined>();
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | undefined>();
    const [tracePanelOpen, setTracePanelOpen] = useState(false);
    const [traceMessageId, setTraceMessageId] = useState<string | undefined>();
    const [showSummary, setShowSummary] = usePersistentChatSummary(
        "feedback-chat-summary-open",
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

    useEffect((): (() => void) => {
        const timeout = setTimeout(() => {
            setPageIndex(0);
        }, 0);
        return (): void => {
            clearTimeout(timeout);
        };
    }, [
        customRange,
        pageSize,
        rating,
        selectedUser?.email,
        selectedUser?.ownerGroup,
        sorting,
        timeRange,
    ]);

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

    const buildFeedbackBaseParams = useCallback(() => {
        const userFilterParams = canFilterUsers
            ? buildUserFilterParams(selectedUser)
            : {};

        return {
            search: searchQuery,
            userEmail: userFilterParams.userEmail,
            userGroup: userFilterParams.userGroup,
            rating: rating === "all" ? undefined : rating,
            sortBy: sorting[0]?.id ?? "created_at",
            descending: sorting[0]?.desc ?? true,
            timeRange,
            customRange,
        };
    }, [
        canFilterUsers,
        customRange,
        rating,
        searchQuery,
        selectedUser,
        sorting,
        timeRange,
    ]);

    useEffect(() => {
        let isMounted = true;
        const load = async (): Promise<void> => {
            setLoading(true);
            setError(undefined);
            try {
                const response = await fetchFeedbackListPage(api, {
                    ...buildFeedbackBaseParams(),
                    limit: pageSize,
                    offset: pageIndex * pageSize,
                });
                if (isMounted) {
                    setPage(response);
                }
            } catch (error_) {
                if (isMounted) {
                    setError(
                        error_ instanceof Error
                            ? error_.message
                            : "Failed to load feedback",
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
    }, [api, buildFeedbackBaseParams, pageIndex, pageSize, refreshToken]);

    const selectedConversationId =
        selectedFeedback?.conversationId ?? search.chat;
    const selectedMessageId = selectedFeedback?.messageId ?? search.message;

    useEffect((): (() => void) => {
        if (!sheetOpen || selectedConversationId === undefined) {
            return (): void => undefined;
        }
        let isMounted = true;
        const loadDetail = async (): Promise<void> => {
            setDetailLoading(true);
            setDetailError(undefined);
            try {
                const response = await fetchChatDetail(
                    api,
                    selectedConversationId,
                    {
                        source: "chats",
                        targetMessageId: selectedMessageId,
                    },
                );
                if (isMounted) {
                    setDetail(response);
                }
            } catch (error_) {
                if (isMounted) {
                    setDetailError(
                        error_ instanceof Error
                            ? error_.message
                            : "Failed to load chat",
                    );
                }
            } finally {
                if (isMounted) {
                    setDetailLoading(false);
                }
            }
        };
        void loadDetail();
        return (): void => {
            isMounted = false;
        };
    }, [
        api,
        selectedConversationId,
        selectedFeedback?.id,
        selectedMessageId,
        sheetOpen,
    ]);

    useEffect((): (() => void) => {
        const timeout = setTimeout(() => {
            if (search.chat !== undefined && search.message !== undefined) {
                setSheetOpen(true);
            }
        }, 0);
        return (): void => {
            clearTimeout(timeout);
        };
    }, [search.chat, search.message]);

    useEffect(() => {
        const baseTitle = `${UNIVERSITY_NAME} Enrollment Assistant`;
        setDocumentTitle(`Feedback · ${baseTitle}`);
    }, []);

    const columns = useMemo(() => buildColumns(), []);
    const tableData = useMemo(() => page?.items ?? [], [page]);
    const pageCount = Math.max(1, Math.ceil((page?.total ?? 0) / pageSize));
    const userOptionsWithOwnerGroups = useMemo(
        () => [...ownerGroupFilterOptions, ...userOptions],
        [ownerGroupFilterOptions, userOptions],
    );
    const selectedUserLabel =
        selectedUser?.name ?? selectedUser?.email ?? "All users";
    const selectedRatingLabel =
        FEEDBACK_RATING_OPTIONS.find((option) => option.value === rating)
            ?.label ?? "All ratings";
    const detailTitle =
        selectedFeedback?.conversationTitle ?? detail?.title ?? "Chat";
    const detailPlatformLabel =
        selectedFeedback?.isPublic === true ? "Public" : "Internal";
    const detailUpdatedAt = selectedFeedback?.updatedAt;
    const selectedIndex = selectedFeedback
        ? tableData.findIndex((row) => row.id === selectedFeedback.id)
        : -1;
    const canGoPrev = selectedIndex > 0;
    const canGoNext =
        selectedIndex >= 0 && selectedIndex < tableData.length - 1;
    const handleRatingChange = (value: FeedbackRatingFilter | null): void => {
        setRating(value ?? "all");
    };
    const handleOverlayFeedbackChange = useCallback((): void => {
        setRefreshToken((value) => value + 1);
    }, []);
    const handleExportFeedback = useCallback(async (): Promise<void> => {
        if (exporting) {
            return;
        }

        setExporting(true);
        try {
            const response = await fetchFeedbackExport(api, {
                ...buildFeedbackBaseParams(),
                ...getFeedbackExportTimeSettings(),
                messageUrlBase: getResponseLinkBaseUrl(),
            });
            downloadFeedbackExcel(response);
            toast.success("Exported feedback");
        } catch (error_) {
            toast.error(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to export feedback",
            );
        } finally {
            setExporting(false);
        }
    }, [api, buildFeedbackBaseParams, exporting]);
    const copyTranscript = useCopyChatTranscript(detail);
    const openChatInNewTab = useCallback(() => {
        if (
            selectedConversationId === undefined ||
            selectedConversationId === ""
        ) {
            return;
        }
        const base = `${window.location.origin}${window.location.pathname}`;
        const url = `${base}#/chats/${selectedConversationId}`;
        window.open(url, "_blank", "noopener,noreferrer");
    }, [selectedConversationId]);
    const openTracePanel = useCallback((messageId: string): void => {
        setTraceMessageId(messageId);
        setTracePanelOpen(true);
    }, []);
    const openFeedback = (row: FeedbackListRow): void => {
        setSelectedFeedback(row);
        setDetailError(undefined);
        setDetailLoading(true);
        setDetail(undefined);
        setSheetOpen(true);
        void navigate({
            to: "/feedback",
            search: {
                chat: row.conversationId,
                message: row.messageId,
            },
        });
    };

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
            focusMessageId={selectedMessageId}
            highlightPhrase={false}
            highlightQuery=""
            loading={detailLoading}
            onFeedbackChange={handleOverlayFeedbackChange}
            onOpenTrace={openTracePanel}
            showSummary={showSummary}
        />
    );

    return (
        <PageShell
            className="overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="Feedback">
                <ReviewTableToolbar
                    canFilterUsers={canFilterUsers}
                    customRange={customRange}
                    extraFilters={
                        <PageHeaderGroup>
                            <Select
                                onValueChange={handleRatingChange}
                                value={rating}
                            >
                                <SelectTrigger
                                    aria-label="Rating"
                                    className="w-[150px]"
                                >
                                    <SelectValue>
                                        {selectedRatingLabel}
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        {FEEDBACK_RATING_OPTIONS.map(
                                            (option) => (
                                                <SelectItem
                                                    key={option.value}
                                                    value={option.value}
                                                >
                                                    {option.label}
                                                </SelectItem>
                                            ),
                                        )}
                                    </SelectGroup>
                                </SelectContent>
                            </Select>
                        </PageHeaderGroup>
                    }
                    onClear={() => {
                        setSearchInput("");
                        setSearchQuery("");
                        setRating("all");
                        setSelectedUser(undefined);
                        setTimeRange("30d");
                        setCustomRange({});
                        setPageIndex(0);
                    }}
                    onCustomRangeChange={setCustomRange}
                    onRefresh={() => {
                        setRefreshToken((value) => value + 1);
                    }}
                    onSearchInputChange={setSearchInput}
                    onSelectedUserChange={(next) => {
                        setSelectedUser(next);
                        setUserPopoverOpen(false);
                    }}
                    onTimeRangeChange={setTimeRange}
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
                <Button
                    disabled={exporting || loading || (page?.total ?? 0) === 0}
                    onClick={() => {
                        void handleExportFeedback();
                    }}
                    variant="outline"
                >
                    <FileSpreadsheet data-icon="inline-start" />
                    {exporting ? "Exporting..." : "Export Excel"}
                </Button>
            </PageHeader>
            <PageSection className="flex min-h-0 flex-1 flex-col">
                {error !== undefined && <InlineError message={error} />}
                <DataTable
                    columns={columns}
                    data={tableData}
                    emptyMessage="No feedback matches your filters"
                    isLoading={loading}
                    isRowSelected={(row) => row.id === selectedFeedback?.id}
                    manualPagination
                    manualSorting
                    onPaginationChange={(updater) => {
                        const next =
                            typeof updater === "function"
                                ? updater({ pageIndex, pageSize })
                                : updater;
                        setPageIndex(next.pageIndex);
                        setPageSize(next.pageSize);
                    }}
                    onRowClick={(row) => {
                        openFeedback(row);
                    }}
                    onSortingChange={setSorting}
                    pageCount={pageCount}
                    pagination={{ pageIndex, pageSize }}
                    rowCount={page?.total ?? 0}
                    sorting={sorting}
                />
            </PageSection>
            <Sheet
                onOpenChange={(open) => {
                    setSheetOpen(open);
                    if (!open) {
                        setDetail(undefined);
                        setDetailError(undefined);
                        setSelectedFeedback(undefined);
                        setTracePanelOpen(false);
                        setTraceMessageId(undefined);
                        void navigate({
                            to: "/feedback",
                            search: { chat: undefined, message: undefined },
                        });
                    }
                }}
                open={sheetOpen}
            >
                <SheetContent
                    className="flex !w-[min(100vw,860px)] !max-w-[min(100vw,860px)] flex-col gap-4 p-0"
                    initialFocus={false}
                >
                    <SheetHeader className="border-b px-4 py-4">
                        <div className="flex items-start justify-between gap-4">
                            <SheetTitle>{detailTitle}</SheetTitle>
                            <ChatReviewSheetActions
                                canGoNext={canGoNext}
                                canGoPrev={canGoPrev}
                                copyDisabled={detail === undefined}
                                nextLabel="Next feedback"
                                onCopyTranscript={() => {
                                    void copyTranscript();
                                }}
                                onGoNext={() => {
                                    if (!canGoNext) {
                                        return;
                                    }
                                    openFeedback(tableData[selectedIndex + 1]);
                                }}
                                onGoPrev={() => {
                                    if (!canGoPrev) {
                                        return;
                                    }
                                    openFeedback(tableData[selectedIndex - 1]);
                                }}
                                onOpenChat={openChatInNewTab}
                                onShowSummaryChange={setShowSummary}
                                openChatDisabled={
                                    selectedConversationId === undefined ||
                                    selectedConversationId === ""
                                }
                                previousLabel="Previous feedback"
                                showSummary={showSummary}
                                summaryToggleId="feedback-summary-toggle"
                            />
                        </div>
                        <SheetDescription>
                            {detailUpdatedAt === undefined ? (
                                "Feedback chat context"
                            ) : (
                                <span className="inline-flex flex-wrap items-center gap-2">
                                    <Badge
                                        variant={
                                            selectedFeedback?.isPublic === true
                                                ? "secondary"
                                                : "outline"
                                        }
                                    >
                                        {detailPlatformLabel}
                                    </Badge>
                                    <span>
                                        Feedback{" "}
                                        {formatTimestamp(detailUpdatedAt)}
                                    </span>
                                </span>
                            )}
                        </SheetDescription>
                    </SheetHeader>
                    <div className="min-h-0 flex-1 overflow-hidden">
                        {detailContent}
                    </div>
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
