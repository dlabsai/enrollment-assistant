import { useNavigate, useSearch } from "@tanstack/react-router";
import type {
    ColumnDef,
    SortingState,
    VisibilityState,
} from "@tanstack/react-table";
import { DEFAULT_HIGHLIGHT_CLASS } from "@va/shared/components/highlighted-text";
import { Badge } from "@va/shared/components/ui/badge";
import { Input } from "@va/shared/components/ui/input";
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
import { X } from "lucide-react";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";

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
    parseRouteDate,
    routeUserOption,
} from "../../chats/lib/review-search-state";
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
import { formatLocaleNumber, formatUsdCost } from "../../lib/number-format";
import { fetchMessageListPage } from "../lib/api";
import type {
    GuardrailStatusFilter,
    MessagePlatformFilter,
    MessageRoleFilter,
    MessagesSearch,
} from "../lib/search-state";
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
            Object.entries(parsed).filter(
                ([, value]) => typeof value === "boolean",
            ),
        );
    } catch {
        return {};
    }
};

const formatCount = (value: number): string => formatLocaleNumber(value);

const formatOptionalCount = (value: number | undefined): string =>
    value === undefined ? "-" : formatCount(value);

const MESSAGE_ROLE_OPTIONS: { label: string; value: MessageRoleFilter }[] = [
    { label: "All roles", value: "all" },
    { label: "User role", value: "user" },
    { label: "Assistant role", value: "assistant" },
];

const isMessageRoleFilter = (
    value: string | null,
): value is MessageRoleFilter =>
    MESSAGE_ROLE_OPTIONS.some((option) => option.value === value);

const PLATFORM_OPTIONS: { label: string; value: MessagePlatformFilter }[] = [
    { label: "All platforms", value: "all" },
    { label: "Internal", value: "internal" },
    { label: "Public", value: "public" },
];

const GUARDRAIL_STATUS_OPTIONS: {
    label: string;
    value: GuardrailStatusFilter;
}[] = [
    { label: "All guardrail outcomes", value: "all" },
    { label: "Required retry", value: "retried" },
    { label: "Final blocked", value: "blocked" },
];

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
        id: "guardrail_retry_count",
        accessorKey: "guardrailRetryCount",
        header: "Chatbot retries",
        enableSorting: true,
        meta: { skeleton: skeletonLine("h-5 w-14") },
        cell: ({ row }): JSX.Element => (
            <div className="text-muted-foreground text-xs tabular-nums">
                {formatOptionalCount(row.original.guardrailRetryCount)}
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
    const routeSearch = useSearch({ from: "/messages" });
    const navigate = useNavigate({ from: "/messages" });
    const canFilterUsers = user?.permissions.access_messages === true;
    const canViewPublic =
        user?.group.slug === "admin" || user?.group.slug === "dev";
    const availablePlatformOptions = useMemo(
        () =>
            canViewPublic
                ? PLATFORM_OPTIONS
                : PLATFORM_OPTIONS.filter(
                      (option) => option.value !== "public",
                  ),
        [canViewPublic],
    );
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

    const requestedPlatform: MessagePlatformFilter =
        routeSearch.platform ?? "all";
    const platform: MessagePlatformFilter =
        requestedPlatform === "public" && !canViewPublic
            ? "all"
            : requestedPlatform;
    const role: MessageRoleFilter = routeSearch.role ?? "assistant";
    const guardrailStatus: GuardrailStatusFilter =
        routeSearch.guardrailStatus ?? "all";
    const excludeDraft = routeSearch.excludeDraft === true;
    const timeRange =
        routeSearch.timeRange ??
        (routeSearch.start === undefined ? "30d" : "custom");
    const customRange = useMemo(
        () => ({
            start: parseRouteDate(routeSearch.start),
            end: parseRouteDate(routeSearch.endBefore ?? routeSearch.end),
        }),
        [routeSearch.end, routeSearch.endBefore, routeSearch.start],
    );
    const selectedUser = useMemo(
        () =>
            routeUserOption(
                routeSearch.userEmail,
                routeSearch.userGroup,
                platform === "all" ? undefined : platform,
            ),
        [platform, routeSearch.userEmail, routeSearch.userGroup],
    );
    const updateSearch = useCallback(
        (updates: Partial<MessagesSearch>): void => {
            void navigate({
                replace: true,
                search: (previous) => ({ ...previous, ...updates }),
                to: "/messages",
            });
        },
        [navigate],
    );

    const searchQuery = routeSearch.search ?? "";
    const [searchDraft, setSearchDraft] = useState(() => ({
        routeValue: searchQuery,
        value: searchQuery,
    }));
    if (searchDraft.routeValue !== searchQuery) {
        setSearchDraft({ routeValue: searchQuery, value: searchQuery });
    }
    const searchInput = searchDraft.value;
    const setSearchInput = (value: string): void => {
        setSearchDraft({ routeValue: searchQuery, value });
    };
    const [userSearchInput, setUserSearchInput] = useState("");
    const [userSearchQuery, setUserSearchQuery] = useState("");
    const [userOptions, setUserOptions] = useState<ChatUserOption[]>([]);
    const [userPopoverOpen, setUserPopoverOpen] = useState(false);
    const [userLoading, setUserLoading] = useState(false);
    const [pageIndex, setPageIndex] = useState(0);
    const [pageSize, setPageSize] = useState(getDefaultDataTablePageSize);
    const sorting = useMemo<SortingState>(
        () => [
            {
                id: routeSearch.sortBy ?? "created_at",
                desc: routeSearch.descending ?? true,
            },
        ],
        [routeSearch.descending, routeSearch.sortBy],
    );
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
            const nextSearch = searchInput.trim();
            if (nextSearch === searchQuery) {
                return;
            }
            updateSearch({
                search: nextSearch === "" ? undefined : nextSearch,
            });
            setPageIndex(0);
        }, 300);
        return (): void => {
            clearTimeout(timeout);
        };
    }, [searchInput, searchQuery, updateSearch]);

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
                    platform: platform === "all" ? undefined : platform,
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
    }, [api, canFilterUsers, platform, userPopoverOpen, userSearchQuery]);

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
                    platform: platform === "all" ? undefined : platform,
                    role,
                    guardrailStatus,
                    minGenerationTimeMs: routeSearch.minGenerationTimeMs,
                    maxGenerationTimeMs: routeSearch.maxGenerationTimeMs,
                    excludeDraft,
                    conversationStart: routeSearch.conversationStart,
                    conversationEnd: routeSearch.conversationEnd,
                    limit: pageSize,
                    offset: pageIndex * pageSize,
                    sortBy: sorting[0]?.id ?? "created_at",
                    descending: sorting[0]?.desc ?? true,
                    timeRange,
                    customRange,
                    endBefore: routeSearch.endBefore,
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
        platform,
        refreshToken,
        role,
        guardrailStatus,
        routeSearch.maxGenerationTimeMs,
        routeSearch.minGenerationTimeMs,
        routeSearch.conversationStart,
        routeSearch.conversationEnd,
        routeSearch.endBefore,
        excludeDraft,
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
        () =>
            platform === "public"
                ? userOptions
                : [...ownerGroupFilterOptions, ...userOptions],
        [ownerGroupFilterOptions, platform, userOptions],
    );
    const selectedUserLabel =
        selectedUser?.name ?? selectedUser?.email ?? "All users";
    const selectedRoleLabel =
        MESSAGE_ROLE_OPTIONS.find((option) => option.value === role)?.label ??
        "Assistant role";
    const selectedPlatformLabel =
        PLATFORM_OPTIONS.find((option) => option.value === platform)?.label ??
        "All platforms";
    const selectedGuardrailStatusLabel =
        GUARDRAIL_STATUS_OPTIONS.find(
            (option) => option.value === guardrailStatus,
        )?.label ?? "All guardrail outcomes";
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
                {(routeSearch.conversationStart !== undefined ||
                    routeSearch.conversationEnd !== undefined) && (
                    <Badge
                        className="gap-1"
                        variant="secondary"
                    >
                        Chats created:{" "}
                        {routeSearch.conversationStart === undefined
                            ? "Any time"
                            : formatTimestamp(routeSearch.conversationStart)}
                        {" – "}
                        {routeSearch.conversationEnd === undefined
                            ? "Any time"
                            : formatTimestamp(routeSearch.conversationEnd)}
                        <button
                            aria-label="Clear chat creation filter"
                            className="hover:bg-muted-foreground/20 focus-visible:ring-ring rounded-sm p-0.5 focus-visible:ring-2 focus-visible:outline-none"
                            onClick={() => {
                                updateSearch({
                                    conversationStart: undefined,
                                    conversationEnd: undefined,
                                });
                                setPageIndex(0);
                            }}
                            type="button"
                        >
                            <X className="size-3" />
                        </button>
                    </Badge>
                )}
                <ReviewTableToolbar
                    canFilterUsers={canFilterUsers}
                    customRange={customRange}
                    extraFilters={
                        <PageHeaderGroup>
                            <Select
                                onValueChange={(value) => {
                                    if (
                                        value === "all" ||
                                        value === "internal" ||
                                        value === "public"
                                    ) {
                                        updateSearch({
                                            platform:
                                                value === "all"
                                                    ? undefined
                                                    : value,
                                            userEmail: undefined,
                                            userGroup: undefined,
                                        });
                                        setPageIndex(0);
                                    }
                                }}
                                value={platform}
                            >
                                <SelectTrigger
                                    aria-label="Platform"
                                    className="w-[150px]"
                                >
                                    <SelectValue>
                                        {selectedPlatformLabel}
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        {availablePlatformOptions.map(
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
                            <Select
                                onValueChange={(value) => {
                                    if (isMessageRoleFilter(value)) {
                                        updateSearch({ role: value });
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
                            <Select
                                onValueChange={(value) => {
                                    if (
                                        value === "all" ||
                                        value === "retried" ||
                                        value === "blocked"
                                    ) {
                                        updateSearch({
                                            guardrailStatus:
                                                value === "all"
                                                    ? undefined
                                                    : value,
                                        });
                                        setPageIndex(0);
                                    }
                                }}
                                value={guardrailStatus}
                            >
                                <SelectTrigger
                                    aria-label="Guardrail outcome"
                                    className="w-[190px]"
                                >
                                    <SelectValue>
                                        {selectedGuardrailStatusLabel}
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        {GUARDRAIL_STATUS_OPTIONS.map(
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
                            <Select
                                onValueChange={(value) => {
                                    updateSearch({
                                        excludeDraft:
                                            value === "live" ? true : undefined,
                                    });
                                    setPageIndex(0);
                                }}
                                value={excludeDraft ? "live" : "all"}
                            >
                                <SelectTrigger
                                    aria-label="Prompt scope"
                                    className="w-[140px]"
                                >
                                    <SelectValue>
                                        {excludeDraft
                                            ? "Live prompts"
                                            : "All prompts"}
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        <SelectItem value="all">
                                            All prompts
                                        </SelectItem>
                                        <SelectItem value="live">
                                            Live prompts
                                        </SelectItem>
                                    </SelectGroup>
                                </SelectContent>
                            </Select>
                            <div className="flex items-center gap-2">
                                <Input
                                    aria-label="Minimum response time in seconds"
                                    className="w-24"
                                    defaultValue={
                                        routeSearch.minGenerationTimeMs ===
                                        undefined
                                            ? ""
                                            : routeSearch.minGenerationTimeMs /
                                              1000
                                    }
                                    key={`min-${routeSearch.minGenerationTimeMs ?? ""}`}
                                    min="0"
                                    onBlur={(event) => {
                                        const seconds = Number(
                                            event.currentTarget.value,
                                        );
                                        updateSearch({
                                            minGenerationTimeMs:
                                                event.currentTarget.value ===
                                                    "" ||
                                                !Number.isFinite(seconds) ||
                                                seconds < 0
                                                    ? undefined
                                                    : seconds * 1000,
                                        });
                                        setPageIndex(0);
                                    }}
                                    placeholder="Min sec"
                                    step="0.1"
                                    type="number"
                                />
                                <Input
                                    aria-label="Maximum response time in seconds"
                                    className="w-24"
                                    defaultValue={
                                        routeSearch.maxGenerationTimeMs ===
                                        undefined
                                            ? ""
                                            : routeSearch.maxGenerationTimeMs /
                                              1000
                                    }
                                    key={`max-${routeSearch.maxGenerationTimeMs ?? ""}`}
                                    min="0"
                                    onBlur={(event) => {
                                        const seconds = Number(
                                            event.currentTarget.value,
                                        );
                                        updateSearch({
                                            maxGenerationTimeMs:
                                                event.currentTarget.value ===
                                                    "" ||
                                                !Number.isFinite(seconds) ||
                                                seconds < 0
                                                    ? undefined
                                                    : seconds * 1000,
                                        });
                                        setPageIndex(0);
                                    }}
                                    placeholder="Max sec"
                                    step="0.1"
                                    type="number"
                                />
                            </div>
                            <DataTableColumnVisibility
                                columnVisibility={columnVisibility}
                                columns={columns}
                                onColumnVisibilityChange={setColumnVisibility}
                            />
                        </PageHeaderGroup>
                    }
                    onClear={() => {
                        setSearchInput("");
                        updateSearch({
                            excludeDraft: undefined,
                            conversationStart: undefined,
                            conversationEnd: undefined,
                            guardrailStatus: undefined,
                            minGenerationTimeMs: undefined,
                            maxGenerationTimeMs: undefined,
                            platform: undefined,
                            role: undefined,
                            search: undefined,
                            start: undefined,
                            end: undefined,
                            endBefore: undefined,
                            timeRange: "30d",
                            userEmail: undefined,
                            userGroup: undefined,
                            sortBy: undefined,
                            descending: undefined,
                        });
                        setPageIndex(0);
                    }}
                    onCustomRangeChange={(value) => {
                        updateSearch({
                            conversationStart: undefined,
                            conversationEnd: undefined,
                            start: value.start?.toISOString(),
                            end: value.end?.toISOString(),
                            endBefore: undefined,
                            timeRange: "custom",
                        });
                        setPageIndex(0);
                    }}
                    onRefresh={() => {
                        setRefreshToken((value) => value + 1);
                    }}
                    onSearchInputChange={setSearchInput}
                    onSelectedUserChange={(option) => {
                        const userFilter = buildUserFilterParams(option);
                        updateSearch({
                            userEmail: userFilter.userEmail,
                            userGroup: userFilter.userGroup,
                        });
                        setUserPopoverOpen(false);
                        setPageIndex(0);
                    }}
                    onTimeRangeChange={(value) => {
                        updateSearch({
                            conversationStart: undefined,
                            conversationEnd: undefined,
                            timeRange: value,
                            endBefore: undefined,
                            start:
                                value === "custom"
                                    ? routeSearch.start
                                    : undefined,
                            end:
                                value === "custom"
                                    ? routeSearch.end
                                    : undefined,
                        });
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
                        const next =
                            typeof updater === "function"
                                ? updater(sorting)
                                : updater;
                        updateSearch({
                            sortBy: next[0]?.id,
                            descending: next[0]?.desc,
                        });
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
