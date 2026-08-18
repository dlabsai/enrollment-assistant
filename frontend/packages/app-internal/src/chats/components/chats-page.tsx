import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Chat } from "@va/shared/components/chat";
import {
    DEFAULT_HIGHLIGHT_CLASS,
    HighlightedText,
} from "@va/shared/components/highlighted-text";
import { LoadingIndicator } from "@va/shared/components/loading-indicator";
import { Streamdown } from "@va/shared/components/streamdown";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import { Input } from "@va/shared/components/ui/input";
import { Label } from "@va/shared/components/ui/label";
import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "@va/shared/components/ui/sheet";
import { Skeleton } from "@va/shared/components/ui/skeleton";
import { Switch } from "@va/shared/components/ui/switch";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { UNIVERSITY_NAME } from "@va/shared/config";
import { setDocumentTitle } from "@va/shared/lib/document-title";
import type { ChatMessage } from "@va/shared/types";
import {
    Copy,
    ExternalLink,
    Filter,
    Link,
    ListTree,
    RefreshCw,
    ThumbsDown,
    ThumbsUp,
} from "lucide-react";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable } from "@/components/data-table";
import { getDefaultDataTablePageSize } from "@/components/data-table-constants";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
import {
    ConversationBranchNavigator,
    ConversationBranchSwitcher,
} from "../../chat/components/conversation-branch-navigation";
import { renderGenerationTimeFooter } from "../../chat/components/generation-time-footer";
import { GuardrailsFooter } from "../../chat/components/guardrails-footer";
import { InvestigationButton } from "../../chat/components/investigation-button";
import {
    MessageFeedback,
    MessageFeedbackDetails,
} from "../../chat/components/message-feedback";
import { useMessageSourcePanelState } from "../../chat/components/message-source-state";
import {
    MessageSourceButtons,
    MessageSourcePanels,
} from "../../chat/components/message-source-ui";
import { renderMessageTimestampFooter } from "../../chat/components/message-timestamp-footer";
import { renderResponseCostFooter } from "../../chat/components/response-cost-footer";
import { useChatStore } from "../../chat/contexts/chat-store-context";
import { ChatStoreProvider } from "../../chat/contexts/chat-store-provider";
import { fetchChatDetail, fetchConversationTree } from "../../chat/lib/api";
import {
    CONVERSATION_BRANCH_LOAD_ERROR,
    type ConversationTreeState,
    convertConversationTree,
    createLatestRequestCoordinator,
    hasConversationBranches,
    hasMessageBranchAlternatives,
    type ReviewConversationDetailSource,
} from "../../chat/lib/conversation-tree";
import { mapServerGuardrailsFailures } from "../../chat/lib/guardrails";
import {
    buildResponseLink,
    openConversationInNewTab,
    type ResponseLinkTarget,
} from "../../chat/lib/response-link";
import type { ChatDetailResponse, Message, Rating } from "../../chat/types";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError, LoadingState } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import { UserFilterPopover } from "../../components/user-filter-popover";
import { formatTableTimestamp } from "../../lib/date-format";
import {
    formatLocaleNumber,
    formatUsdCost,
} from "../../lib/number-format";
import {
    type CustomTimeRange,
    isTimeRangeValue,
    type TimeRangeValue,
} from "../../lib/time-range";
import {
    useCopyChatTranscript,
    usePersistentChatSummary,
} from "../hooks/use-chat-review-controls";
import { fetchChatListPage, fetchChatUsers } from "../lib/api";
import {
    buildOwnerGroupFilterOptions,
    buildUserFilterParams,
    parseStoredUserFilter,
} from "../lib/user-filter-options";
import type {
    ChatListPage as ChatListPageResponse,
    ChatListRow,
    ChatUserOption,
} from "../types";
import { ChatReviewSheetActions } from "./chat-review-sheet-actions";
import { ChatTurnTraceSheet } from "./chat-turn-trace-sheet";

const formatTimestamp = formatTableTimestamp;

const skeletonLine = (className: string): JSX.Element => (
    <Skeleton className={className} />
);

const chatSkeleton: JSX.Element = (
    <div className="w-full min-w-0 space-y-1">
        {skeletonLine("h-5 w-3/4")}
        {skeletonLine("h-4 w-11/12")}
    </div>
);

const userSkeleton: JSX.Element = (
    <div className="w-full min-w-0">
        {skeletonLine("h-5 w-2/3")}
        {skeletonLine("h-4 w-1/2")}
    </div>
);

const buildColumns = (
    query: string,
    phrase: boolean,
    showPlatformColumn: boolean,
    canViewCost: boolean,
    titleHeader: string,
    showFeedbackColumn: boolean,
): ColumnDef<ChatListRow>[] => {
    const columns: ColumnDef<ChatListRow>[] = [
        {
            id: "title",
            accessorKey: "title",
            header: titleHeader,
            meta: {
                skeleton: chatSkeleton,
            },
            cell: ({ row }): JSX.Element => {
                const title = row.original.title ?? "Untitled chat";
                const preview = row.original.lastMessagePreview ?? "";

                return (
                    <div className="min-w-0 space-y-1">
                        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold">
                            <span className="min-w-0 truncate">
                                <HighlightedText
                                    phrase={phrase}
                                    query={query}
                                    text={title}
                                />
                            </span>
                            {row.original.promptSource === "draft" && (
                                <Badge
                                    className="shrink-0"
                                    variant="secondary"
                                >
                                    Draft instructions
                                </Badge>
                            )}
                        </div>
                        {preview !== "" && (
                            <div className="text-muted-foreground line-clamp-2 text-xs">
                                <HighlightedText
                                    phrase={phrase}
                                    query={query}
                                    text={preview}
                                />
                            </div>
                        )}
                    </div>
                );
            },
        },
        {
            id: "user",
            header: "User",
            meta: {
                skeleton: userSkeleton,
            },
            cell: ({ row }): JSX.Element => {
                const name = row.original.userName ?? "-";
                const email = row.original.userEmail;

                return (
                    <div className="min-w-0">
                        <div className="truncate text-sm">{name}</div>
                        {email !== undefined && email !== "" && (
                            <div className="text-muted-foreground truncate text-xs">
                                {email}
                            </div>
                        )}
                    </div>
                );
            },
        },
        ...(showPlatformColumn
            ? [
                  {
                      id: "platform",
                      header: "Platform",
                      meta: {
                          skeleton: skeletonLine("h-6 w-20 rounded-full"),
                      },
                      cell: ({
                          row,
                      }: {
                          row: { original: ChatListRow };
                      }): JSX.Element => (
                          <Badge
                              variant={
                                  row.original.isPublic
                                      ? "secondary"
                                      : "outline"
                              }
                          >
                              {row.original.isPublic ? "Public" : "Internal"}
                          </Badge>
                      ),
                  },
              ]
            : []),
        {
            id: "user_message_count",
            accessorKey: "userMessageCount",
            header: "User messages",
            enableSorting: true,
            meta: {
                skeleton: skeletonLine("h-4 w-12"),
            },
            cell: ({ row }): JSX.Element => (
                <div className="tabular-nums">
                    {formatLocaleNumber(row.original.userMessageCount)}
                </div>
            ),
        },
        {
            id: "assistant_message_count",
            accessorKey: "assistantMessageCount",
            header: "Assistant messages",
            enableSorting: true,
            meta: {
                skeleton: skeletonLine("h-4 w-12"),
            },
            cell: ({ row }): JSX.Element => (
                <div className="tabular-nums">
                    {formatLocaleNumber(row.original.assistantMessageCount)}
                </div>
            ),
        },
        ...(canViewCost
            ? [
                  {
                      id: "total_cost",
                      accessorKey: "totalCost",
                      header: "Cost",
                      enableSorting: true,
                      meta: {
                          skeleton: skeletonLine("h-4 w-16"),
                      },
                      cell: ({
                          row,
                      }: {
                          row: { original: ChatListRow };
                      }): JSX.Element => (
                          <div className="tabular-nums">
                              {formatUsdCost(row.original.totalCost)}
                          </div>
                      ),
                  },
              ]
            : []),
        ...(showFeedbackColumn
            ? [
                  {
                      id: "feedback_up",
                      accessorKey: "feedbackUp",
                      header: "Feedback",
                      enableSorting: true,
                      meta: {
                          skeleton: (
                              <div className="flex items-center gap-3">
                                  {skeletonLine("h-4 w-12")}
                                  {skeletonLine("h-4 w-12")}
                              </div>
                          ),
                      },
                      cell: ({
                          row,
                      }: {
                          row: { original: ChatListRow };
                      }): JSX.Element => (
                          <div className="flex items-center gap-3 text-xs tabular-nums">
                              <span
                                  className={
                                      row.original.feedbackUp > 0
                                          ? "inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400"
                                          : "text-muted-foreground inline-flex items-center gap-1"
                                  }
                              >
                                  <ThumbsUp className="size-3" />
                                  {formatLocaleNumber(row.original.feedbackUp)}
                              </span>
                              <span
                                  className={
                                      row.original.feedbackDown > 0
                                          ? "text-destructive inline-flex items-center gap-1"
                                          : "text-muted-foreground inline-flex items-center gap-1"
                                  }
                              >
                                  <ThumbsDown className="size-3" />
                                  {formatLocaleNumber(
                                      row.original.feedbackDown,
                                  )}
                              </span>
                          </div>
                      ),
                  },
              ]
            : []),
        {
            id: "updated_at",
            accessorKey: "updatedAt",
            header: "Updated",
            enableSorting: true,
            meta: {
                skeleton: skeletonLine("h-3 w-24"),
            },
            cell: ({ row }): JSX.Element => (
                <div className="text-muted-foreground text-xs">
                    {formatTimestamp(row.original.updatedAt)}
                </div>
            ),
        },
    ];

    return columns;
};

const toChatMessages = (detail: ChatDetailResponse): ChatMessage[] =>
    detail.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content:
            message.guardrails_blocked === true &&
            typeof message.guardrails_blocked_message === "string" &&
            message.guardrails_blocked_message !== ""
                ? message.guardrails_blocked_message
                : message.content,
        timestamp: new Date(message.created_at).getTime(),
        toolSourcesUsed: message.tool_sources_used,
        groundingSourcesUsed: message.grounding_sources_used,
        groundingSourceStatus: message.grounding_source_status,
    }));

const toInternalMessage = (
    message: ChatDetailResponse["messages"][number],
): Message => ({
    id: message.id,
    role: message.role,
    content:
        message.guardrails_blocked === true &&
        typeof message.guardrails_blocked_message === "string" &&
        message.guardrails_blocked_message !== ""
            ? message.guardrails_blocked_message
            : message.content,
    createdAt: new Date(message.created_at).getTime(),
    parentId: message.parent_id ?? undefined,
    guardrailsBlocked: message.guardrails_blocked ?? false,
    guardrailsBlockedMessage: message.guardrails_blocked_message ?? undefined,
    assistantToolCalls: message.assistant_tool_calls,
    generationTimeMs: message.generation_time_ms,
    generationTiming:
        message.generation_timing === undefined
            ? undefined
            : {
                  totalTimeMs: message.generation_timing.total_time_ms,
                  chatbotTimeMs: message.generation_timing.chatbot_time_ms,
                  guardrailTimeMs: message.generation_timing.guardrail_time_ms,
                  chatbotTimesMs: message.generation_timing.chatbot_times_ms,
                  guardrailTimesMs:
                      message.generation_timing.guardrail_times_ms,
                  chatbotModel: message.generation_timing.chatbot_model,
                  guardrailModel: message.generation_timing.guardrail_model,
              },
    responseCost: message.response_cost ?? undefined,
    responseUsage:
        message.response_usage === undefined || message.response_usage === null
            ? undefined
            : {
                  inputTokens: message.response_usage.input_tokens ?? undefined,
                  uncachedInputTokens:
                      message.response_usage.uncached_input_tokens ?? undefined,
                  cacheReadInputTokens:
                      message.response_usage.cache_read_input_tokens ??
                      undefined,
                  outputTokens:
                      message.response_usage.output_tokens ?? undefined,
              },
    responseCostBreakdown:
        message.response_cost_breakdown === undefined ||
        message.response_cost_breakdown === null
            ? undefined
            : {
                  inputCost:
                      message.response_cost_breakdown.input_cost ?? undefined,
                  cacheReadInputCost:
                      message.response_cost_breakdown.cache_read_input_cost ??
                      undefined,
                  outputCost:
                      message.response_cost_breakdown.output_cost ?? undefined,
              },
    guardrailsFailures: mapServerGuardrailsFailures(
        message.guardrails_failures,
    ),
    toolSourcesUsed: message.tool_sources_used,
    groundingSourcesUsed: message.grounding_sources_used,
    groundingSourceStatus: message.grounding_source_status,
});

const platformOptions = [
    { label: "All platforms", value: "both" },
    { label: "Internal", value: "internal" },
    { label: "Public", value: "public" },
] as const;

const SHOW_PLATFORM_FILTER = false;

const chatFilterStorageKeys = {
    chat: "internal-chat-filters",
    investigation: "internal-investigation-filters",
} as const;

type ReviewCollectionKind = keyof typeof chatFilterStorageKeys;

type ReviewRoutePath = "/chats" | "/investigations";

interface ReviewPageProps {
    kind?: ReviewCollectionKind;
    routePath?: ReviewRoutePath;
    title?: string;
}

interface FeedbackChange {
    previous?: Rating;
    next?: Rating;
}

type ChatDetailLoadState =
    | { chatId: string; detail: ChatDetailResponse; error?: never }
    | { chatId: string; detail?: never; error: string };

type PlatformFilter = (typeof platformOptions)[number]["value"];

interface StoredChatFilters {
    platform?: PlatformFilter;
    timeRange?: TimeRangeValue;
    customRange?: {
        start?: string;
        end?: string;
    };
    searchInput?: string;
    phraseSearch?: boolean;
    highlightMatches?: boolean;
    selectedUser?: ChatUserOption;
}

const isPlatformFilter = (value: string): value is PlatformFilter =>
    platformOptions.some((option) => option.value === value);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

const parseStoredDate = (value?: string): Date | undefined => {
    if (value === undefined || value === "") {
        return undefined;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

const parseStoredCustomRange = (
    range?: StoredChatFilters["customRange"],
): CustomTimeRange => ({
    start: parseStoredDate(range?.start),
    end: parseStoredDate(range?.end),
});

const parseStoredChatFilters = (
    value: string,
): StoredChatFilters | undefined => {
    try {
        const parsed: unknown = JSON.parse(value);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const customRangeValue = isRecord(parsed.customRange)
            ? parsed.customRange
            : undefined;
        const platformValue =
            typeof parsed.platform === "string" &&
            isPlatformFilter(parsed.platform)
                ? parsed.platform
                : undefined;
        const timeRangeValue =
            typeof parsed.timeRange === "string" &&
            isTimeRangeValue(parsed.timeRange)
                ? parsed.timeRange
                : undefined;
        return {
            platform: platformValue,
            timeRange: timeRangeValue,
            searchInput:
                typeof parsed.searchInput === "string"
                    ? parsed.searchInput
                    : undefined,
            phraseSearch:
                typeof parsed.phraseSearch === "boolean"
                    ? parsed.phraseSearch
                    : undefined,
            highlightMatches:
                typeof parsed.highlightMatches === "boolean"
                    ? parsed.highlightMatches
                    : undefined,
            customRange: {
                start:
                    typeof customRangeValue?.start === "string"
                        ? customRangeValue.start
                        : undefined,
                end:
                    typeof customRangeValue?.end === "string"
                        ? customRangeValue.end
                        : undefined,
            },
            selectedUser: parseStoredUserFilter(parsed.selectedUser),
        };
    } catch {
        return undefined;
    }
};

const getStoredChatFilters = (
    storageKey: string,
): StoredChatFilters | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const stored = window.localStorage.getItem(storageKey);
    if (stored === null || stored === "") {
        return undefined;
    }
    return parseStoredChatFilters(stored);
};

const DetailFeedbackInitializer = ({
    detail,
}: {
    detail: ChatDetailResponse;
}): undefined => {
    const initializeMessageFeedback = useChatStore(
        (state) => state.initializeMessageFeedback,
    );

    useEffect(() => {
        initializeMessageFeedback(
            detail.messages.map((message) => ({
                messageId: message.id,
                feedback: message.feedback ?? [],
            })),
        );
    }, [detail, initializeMessageFeedback]);

    return undefined;
};

interface ReviewConversationTreeResult {
    context: string;
    tree?: ConversationTreeState;
    error?: string;
}

interface PendingBranchNavigation {
    context: string;
}

interface ReviewBranchFocus extends PendingBranchNavigation {
    detail: ChatDetailResponse;
    messageId: string;
}

interface ChatDetailContentProps {
    canViewDurationTooltip: boolean;
    canViewResponseCost: boolean;
    canViewGuardrailsFailures: boolean;
    canViewSources: boolean;
    canViewTools: boolean;
    canViewTrace: boolean;
    detail: ChatDetailResponse | undefined;
    error: string | undefined;
    focusMessageId?: string;
    highlightPhrase: boolean;
    highlightQuery: string;
    loading: boolean;
    onDetailChange: (detail: ChatDetailResponse) => void;
    onFeedbackChange: (change: FeedbackChange) => void;
    onOpenTrace: (messageId: string) => void;
    responseLinkTarget?: ResponseLinkTarget;
    source: ReviewConversationDetailSource;
    showFeedback?: boolean;
    showInvestigations?: boolean;
    showSummary: boolean;
}

export const ChatDetailContent = ({
    canViewDurationTooltip,
    canViewResponseCost,
    canViewGuardrailsFailures,
    canViewSources,
    canViewTools,
    canViewTrace,
    detail,
    error,
    focusMessageId,
    highlightPhrase,
    highlightQuery,
    loading,
    onDetailChange,
    onFeedbackChange,
    onOpenTrace,
    responseLinkTarget = "chat",
    source,
    showFeedback = true,
    showInvestigations = true,
    showSummary,
}: ChatDetailContentProps): JSX.Element => {
    const api = useAuthenticatedApi();
    const detailRequests = useMemo(() => createLatestRequestCoordinator(), []);
    const conversationId = detail?.id;
    const treeContext =
        conversationId === undefined
            ? undefined
            : `${source}:${conversationId}`;
    const branchNavigationContext =
        treeContext === undefined
            ? undefined
            : `${treeContext}:${focusMessageId ?? ""}`;
    const [conversationTreeResult, setConversationTreeResult] =
        useState<ReviewConversationTreeResult>();
    const activeConversationTreeResult =
        conversationTreeResult?.context === treeContext
            ? conversationTreeResult
            : undefined;
    const conversationTree = activeConversationTreeResult?.tree;
    const conversationTreeError = activeConversationTreeResult?.error;
    const [branchFocus, setBranchFocus] = useState<ReviewBranchFocus>();
    const branchFocusMessageId =
        branchFocus !== undefined &&
        branchFocus.context === branchNavigationContext &&
        branchFocus.detail === detail
            ? branchFocus.messageId
            : focusMessageId;
    const [pendingBranchNavigation, setPendingBranchNavigation] =
        useState<PendingBranchNavigation>();
    const branchNavigationLoading =
        pendingBranchNavigation?.context === branchNavigationContext;
    const conversationTreeRequests = useMemo(
        () => createLatestRequestCoordinator(),
        [],
    );

    useEffect(
        () => (): void => {
            detailRequests.invalidate();
        },
        [branchNavigationContext, detailRequests, loading],
    );
    const messages = useMemo(
        (): ChatMessage[] => (detail ? toChatMessages(detail) : []),
        [detail],
    );
    const detailMessageById = useMemo(() => {
        const map = new Map<string, Message>();
        for (const message of detail?.messages ?? []) {
            map.set(message.id, toInternalMessage(message));
        }
        return map;
    }, [detail]);
    const copyResponseLink = useCallback(
        async (messageId: string): Promise<void> => {
            if (detail === undefined) {
                return;
            }
            try {
                await navigator.clipboard.writeText(
                    buildResponseLink(detail.id, messageId, responseLinkTarget),
                );
                toast.success("Copied response link");
            } catch {
                toast.error("Failed to copy response link");
            }
        },
        [detail, responseLinkTarget],
    );
    const sourcePanelState = useMessageSourcePanelState();
    const viewedPath = useMemo(
        () => detail?.messages.map((message) => message.id) ?? [],
        [detail],
    );

    const loadReviewConversationTree = useCallback((): void => {
        if (conversationId === undefined || treeContext === undefined) {
            return;
        }
        void conversationTreeRequests
            .run(async () =>
                convertConversationTree(
                    await fetchConversationTree(api, conversationId, {
                        source,
                    }),
                ),
            )
            .then(
                (result) => {
                    if (result.status === "current") {
                        setConversationTreeResult({
                            context: treeContext,
                            tree: result.value,
                        });
                    }
                },
                () => {
                    setConversationTreeResult({
                        context: treeContext,
                        error: CONVERSATION_BRANCH_LOAD_ERROR,
                    });
                },
            );
    }, [api, conversationId, conversationTreeRequests, source, treeContext]);

    useEffect(() => {
        loadReviewConversationTree();
        return (): void => {
            conversationTreeRequests.invalidate();
        };
    }, [conversationTreeRequests, loadReviewConversationTree]);

    const handleSelectReviewMessage = useCallback(
        async (messageId: string): Promise<boolean> => {
            if (
                detail === undefined ||
                branchNavigationContext === undefined ||
                branchNavigationLoading
            ) {
                return false;
            }
            const requestContext = branchNavigationContext;
            if (viewedPath.includes(messageId)) {
                setBranchFocus({
                    context: requestContext,
                    detail,
                    messageId,
                });
                return true;
            }

            const pendingRequest: PendingBranchNavigation = {
                context: requestContext,
            };
            setPendingBranchNavigation(pendingRequest);
            try {
                const result = await detailRequests.run(async () =>
                    fetchChatDetail(api, detail.id, {
                        source,
                        targetMessageId: messageId,
                    }),
                );
                if (result.status === "stale") {
                    return false;
                }
                onDetailChange(result.value);
                setBranchFocus({
                    context: requestContext,
                    detail: result.value,
                    messageId,
                });
                return true;
            } catch {
                toast.error("Failed to switch branch");
                return false;
            } finally {
                setPendingBranchNavigation((pending) =>
                    pending === pendingRequest ? undefined : pending,
                );
            }
        },
        [
            api,
            branchNavigationContext,
            branchNavigationLoading,
            detail,
            detailRequests,
            onDetailChange,
            source,
            viewedPath,
        ],
    );

    if (loading) {
        return <LoadingState />;
    }

    if (error !== undefined) {
        return (
            <div className="text-destructive flex h-full items-center justify-center px-6 text-center text-sm">
                {error}
            </div>
        );
    }

    if (detail === undefined) {
        return (
            <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
                Select a chat to view.
            </div>
        );
    }

    const renderBranchHeader = (): JSX.Element | undefined => {
        if (conversationTreeError !== undefined) {
            return (
                <div className="px-3 pt-3">
                    <InlineError
                        className="mb-0"
                        message={conversationTreeError}
                        onRetry={loadReviewConversationTree}
                    />
                </div>
            );
        }
        if (hasConversationBranches(conversationTree)) {
            return (
                <div className="flex justify-end px-3 py-2">
                    <ConversationBranchNavigator
                        disabled={branchNavigationLoading}
                        loading={branchNavigationLoading}
                        mode="review"
                        onSelectMessage={handleSelectReviewMessage}
                        tree={conversationTree}
                        viewedPath={viewedPath}
                    />
                </div>
            );
        }
        return undefined;
    };
    const branchHeader = renderBranchHeader();

    const chatPanel = (
        <ChatStoreProvider>
            {showFeedback && <DetailFeedbackInitializer detail={detail} />}
            <Chat
                autoScroll={false}
                canSendMessages={false}
                contentWidthMode="standard"
                disableVoiceFeatures
                focusMessageId={branchFocusMessageId}
                headerContent={branchHeader}
                highlightPhrase={highlightPhrase}
                highlightQuery={highlightQuery}
                isLoading={false}
                key={`${detail.id}-${highlightQuery}-${highlightPhrase}`}
                loadingIndicatorComponent={LoadingIndicator}
                messages={messages}
                messagesInitialized
                onSendMessage={(): void => undefined}
                renderMessageBelowContent={(
                    message,
                ): JSX.Element | undefined => {
                    const isEligibleAssistantMessage =
                        message.role === "assistant" &&
                        !message.id.startsWith("error-");
                    if (!isEligibleAssistantMessage) {
                        return undefined;
                    }

                    const feedbackDetails = showFeedback ? (
                        <MessageFeedbackDetails messageId={message.id} />
                    ) : undefined;

                    return (
                        <div className="space-y-2">
                            <MessageSourcePanels
                                canViewSources={canViewSources}
                                canViewTools={canViewTools}
                                message={message}
                                state={sourcePanelState}
                            />
                            {feedbackDetails}
                        </div>
                    );
                }}
                renderMessageFooter={(message): JSX.Element | undefined => {
                    const isEligibleAssistantMessage =
                        message.role === "assistant" &&
                        !message.id.startsWith("error-");
                    const branchSwitcher = hasMessageBranchAlternatives(
                        conversationTree,
                        message.id,
                    ) ? (
                        <ConversationBranchSwitcher
                            currentMessageId={message.id}
                            disabled={branchNavigationLoading}
                            onSelectMessage={handleSelectReviewMessage}
                            tree={conversationTree}
                        />
                    ) : undefined;
                    const sourceButtons = isEligibleAssistantMessage ? (
                        <MessageSourceButtons
                            canViewSources={canViewSources}
                            canViewTools={canViewTools}
                            message={message}
                            state={sourcePanelState}
                        />
                    ) : undefined;

                    if (
                        !isEligibleAssistantMessage &&
                        sourceButtons === undefined &&
                        branchSwitcher === undefined
                    ) {
                        return undefined;
                    }

                    return (
                        <div className="flex flex-wrap items-center gap-1">
                            {isEligibleAssistantMessage && showFeedback ? (
                                <MessageFeedback
                                    feedbackSource="chats"
                                    hideOtherFeedbacksPopover
                                    messageId={message.id}
                                    onFeedbackChange={onFeedbackChange}
                                />
                            ) : undefined}
                            {sourceButtons}
                            {branchSwitcher}
                        </div>
                    );
                }}
                renderMessageFooterAside={(
                    message,
                ): JSX.Element | undefined => {
                    const internalMessage = detailMessageById.get(message.id);
                    const timingFooter = renderGenerationTimeFooter(
                        internalMessage,
                        canViewDurationTooltip,
                    );
                    const timestampFooter =
                        renderMessageTimestampFooter(internalMessage);
                    const responseCostFooter = renderResponseCostFooter(
                        internalMessage,
                        canViewResponseCost,
                    );
                    const guardrailsFooter =
                        canViewGuardrailsFailures &&
                        internalMessage?.role === "assistant" &&
                        (internalMessage.guardrailsFailures?.length ?? 0) >
                            0 ? (
                            <GuardrailsFooter message={internalMessage} />
                        ) : undefined;
                    const responseLinkButton =
                        canViewResponseCost &&
                        message.role === "assistant" &&
                        !message.id.startsWith("error-") ? (
                            <TooltipProvider delay={0}>
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                aria-label="Copy response link"
                                                className="rounded-full"
                                                onClick={() => {
                                                    void copyResponseLink(
                                                        message.id,
                                                    );
                                                }}
                                                size="icon-sm"
                                                type="button"
                                                variant="ghost"
                                            >
                                                <Link />
                                            </Button>
                                        }
                                    />
                                    <TooltipContent>
                                        Copy response link
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        ) : undefined;
                    const investigationButton =
                        showInvestigations &&
                        message.role === "assistant" &&
                        !message.id.startsWith("error-") ? (
                            <InvestigationButton
                                conversationId={detail.id}
                                messageId={message.id}
                                withProvider
                            />
                        ) : undefined;
                    const traceButton =
                        canViewTrace &&
                        message.role === "assistant" &&
                        !message.id.startsWith("error-") ? (
                            <TooltipProvider delay={0}>
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                aria-label="Trace"
                                                className="rounded-full"
                                                onClick={() => {
                                                    onOpenTrace(message.id);
                                                }}
                                                size="icon-sm"
                                                type="button"
                                                variant="ghost"
                                            >
                                                <ListTree />
                                            </Button>
                                        }
                                    />
                                    <TooltipContent>Trace</TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        ) : undefined;

                    if (
                        timestampFooter === undefined &&
                        timingFooter === undefined &&
                        responseCostFooter === undefined &&
                        guardrailsFooter === undefined &&
                        responseLinkButton === undefined &&
                        investigationButton === undefined &&
                        traceButton === undefined
                    ) {
                        return undefined;
                    }
                    return (
                        <div className="flex items-center gap-1">
                            {timestampFooter}
                            {timingFooter}
                            {responseCostFooter}
                            {guardrailsFooter}
                            {responseLinkButton}
                            {investigationButton}
                            {traceButton}
                        </div>
                    );
                }}
                useNativeScrollbar
            />
        </ChatStoreProvider>
    );

    if (!showSummary) {
        return (
            <div className="h-full min-h-0 overflow-hidden">{chatPanel}</div>
        );
    }

    return (
        <ResizablePanelGroup
            className="min-h-0 flex-1"
            id="chats-detail-layout"
            orientation="vertical"
        >
            <ResizablePanel
                className="min-h-0"
                defaultSize="30%"
                id="chats-detail-summary-panel"
                maxSize="60%"
                minSize="20%"
            >
                <div className="flex h-full min-h-0 flex-col border-b pr-0 pl-4">
                    <div className="min-h-0 flex-1 overflow-auto pr-4 text-sm leading-relaxed">
                        {detail.summary !== undefined &&
                        detail.summary.trim() !== "" ? (
                            <Streamdown className="max-w-none break-words">
                                {detail.summary}
                            </Streamdown>
                        ) : (
                            <span className="text-muted-foreground">
                                Summary will appear once generated for this
                                chat.
                            </span>
                        )}
                    </div>
                </div>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel
                className="min-h-0"
                id="chats-detail-chat-panel"
                minSize="40%"
            >
                <div className="h-full min-h-0 overflow-hidden">
                    {chatPanel}
                </div>
            </ResizablePanel>
        </ResizablePanelGroup>
    );
};

const ChatReviewListPage = ({
    kind = "chat",
    routePath = "/chats",
    title = "Chats",
}: ReviewPageProps): JSX.Element => {
    const api = useAuthenticatedApi();
    const { user } = useAuth();
    const canViewOwn = hasPermission(user, "chats_view_own");
    const canViewUsers = hasPermission(user, "chats_view_users");
    const canViewAdmins = hasPermission(user, "chats_view_admins");
    const canViewDevs = hasPermission(user, "chats_view_devs");
    const canViewTrace = hasPermission(user, "chats_view_trace");
    const canViewDurationTooltip = hasPermission(user, "chat_duration_tooltip");
    const canViewResponseCost = hasPermission(user, "chat_view_response_cost");
    const canViewGuardrailsFailures = hasPermission(
        user,
        "chat_view_guardrails_failures",
    );
    const canViewSources = hasPermission(user, "chat_view_sources");
    const canViewTools = hasPermission(user, "chat_view_tools");
    const canViewCost = hasPermission(user, "chats_view_cost_column");
    const canViewAnyOwnerGroup = canViewUsers || canViewAdmins || canViewDevs;
    const canViewPublic =
        kind === "chat" &&
        (user?.group.slug === "admin" || user?.group.slug === "dev");
    const canViewCurrentUserByGroup =
        user?.group.slug === "user"
            ? canViewUsers
            : user?.group.slug === "admin"
              ? canViewAdmins
              : user?.group.slug === "dev"
                ? canViewDevs
                : false;
    const canViewCurrentUserChats = canViewOwn || canViewCurrentUserByGroup;
    const canFilterUsers = canViewPublic || canViewAnyOwnerGroup;
    const ownerGroupFilterOptions = useMemo(
        () => buildOwnerGroupFilterOptions(user),
        [user],
    );
    const search = useSearch({ from: routePath });
    const navigate = useNavigate();
    const storageKey = chatFilterStorageKeys[kind];
    const showPlatformFilter = kind === "chat" && SHOW_PLATFORM_FILTER;
    const itemName = kind === "investigation" ? "investigation" : "chat";
    const itemNamePlural =
        kind === "investigation" ? "investigations" : "chats";
    const titleColumnHeader =
        kind === "investigation" ? "Investigation" : "Chat";
    const storedFilters = useMemo(
        () => getStoredChatFilters(storageKey),
        [storageKey],
    );
    const [searchInput, setSearchInput] = useState(
        storedFilters?.searchInput ?? "",
    );
    const [searchQuery, setSearchQuery] = useState(
        storedFilters?.searchInput?.trim() ?? "",
    );
    const [phraseSearch, setPhraseSearch] = useState(
        storedFilters?.phraseSearch ?? true,
    );
    const [highlightMatches, setHighlightMatches] = useState(
        storedFilters?.highlightMatches ?? true,
    );
    const [userSearchInput, setUserSearchInput] = useState("");
    const [userSearchQuery, setUserSearchQuery] = useState("");
    const [userOptions, setUserOptions] = useState<ChatUserOption[]>([]);
    const [userPopoverOpen, setUserPopoverOpen] = useState(false);
    const [userLoading, setUserLoading] = useState(false);
    const [selectedUserState, setSelectedUserState] = useState<
        ChatUserOption | undefined
    >(storedFilters?.selectedUser);
    const selectedUser = canFilterUsers ? selectedUserState : undefined;
    const currentUserOption = useMemo<ChatUserOption | undefined>(
        () =>
            canViewCurrentUserChats &&
            user?.email !== undefined &&
            user.email !== ""
                ? {
                      name: user.name || undefined,
                      email: user.email,
                      platform: "internal",
                  }
                : undefined,
        [canViewCurrentUserChats, user],
    );
    const [showSummary, setShowSummary] = usePersistentChatSummary(
        "internal-chat-summary-open",
    );
    const [platform, setPlatform] = useState<PlatformFilter>(() => {
        if (!showPlatformFilter) {
            return "both";
        }
        const storedPlatform = storedFilters?.platform;
        if (storedPlatform !== undefined) {
            return storedPlatform;
        }
        return "both";
    });
    const [timeRange, setTimeRange] = useState<TimeRangeValue>(() => {
        const storedTimeRange = storedFilters?.timeRange;
        if (storedTimeRange !== undefined) {
            return storedTimeRange;
        }
        return "30d";
    });
    const [customRange, setCustomRange] = useState<CustomTimeRange>(() =>
        parseStoredCustomRange(storedFilters?.customRange),
    );
    const [pageIndex, setPageIndex] = useState(0);
    const [pageSize, setPageSize] = useState(getDefaultDataTablePageSize);
    const [sorting, setSorting] = useState<SortingState>([
        { id: "updated_at", desc: true },
    ]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | undefined>();
    const [page, setPage] = useState<ChatListPageResponse | undefined>();
    const [refreshToken, setRefreshToken] = useState(0);

    const [detailLoadState, setDetailLoadState] =
        useState<ChatDetailLoadState>();
    const [tracePanelOpen, setTracePanelOpen] = useState(false);
    const [traceMessageId, setTraceMessageId] = useState<string | undefined>();
    const requestPlatform =
        kind === "investigation"
            ? "internal"
            : platform === "both"
              ? undefined
              : platform;
    const tableData = useMemo(() => page?.items ?? [], [page]);
    const selectedChat =
        search.chat === undefined
            ? undefined
            : tableData.find((row) => row.id === search.chat);
    const selectedChatId = selectedChat?.id;
    const sheetOpen = selectedChat !== undefined;
    const activeDetailLoadState =
        detailLoadState?.chatId === selectedChatId
            ? detailLoadState
            : undefined;
    const detail = activeDetailLoadState?.detail;
    const detailError = activeDetailLoadState?.error;
    const activeDetailLoading = sheetOpen && activeDetailLoadState === undefined;

    const applyFeedbackChange = useCallback(
        (change: FeedbackChange): void => {
            if (!selectedChat) {
                return;
            }

            const deltaUp =
                (change.previous === "thumbs_up" ? -1 : 0) +
                (change.next === "thumbs_up" ? 1 : 0);
            const deltaDown =
                (change.previous === "thumbs_down" ? -1 : 0) +
                (change.next === "thumbs_down" ? 1 : 0);

            if (deltaUp === 0 && deltaDown === 0) {
                return;
            }

            setPage((prev) => {
                if (!prev) {
                    return prev;
                }

                return {
                    ...prev,
                    items: prev.items.map((item) => {
                        if (item.id !== selectedChat.id) {
                            return item;
                        }
                        return {
                            ...item,
                            feedbackUp: Math.max(0, item.feedbackUp + deltaUp),
                            feedbackDown: Math.max(
                                0,
                                item.feedbackDown + deltaDown,
                            ),
                        };
                    }),
                };
            });
        },
        [selectedChat],
    );

    useEffect((): (() => void) => {
        const timeout = setTimeout(() => {
            setSearchQuery(searchInput.trim());
            setPageIndex(0);
        }, 300);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [searchInput]);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        const payload: StoredChatFilters = {
            platform,
            timeRange,
            customRange: {
                start: customRange.start?.toISOString(),
                end: customRange.end?.toISOString(),
            },
            searchInput,
            phraseSearch,
            highlightMatches,
            selectedUser: selectedUser
                ? {
                      email: selectedUser.email,
                      name: selectedUser.name,
                      ownerGroup: selectedUser.ownerGroup,
                      platform: selectedUser.platform,
                  }
                : undefined,
        };
        window.localStorage.setItem(storageKey, JSON.stringify(payload));
    }, [
        customRange,
        highlightMatches,
        phraseSearch,
        platform,
        searchInput,
        selectedUser,
        storageKey,
        timeRange,
    ]);

    useEffect((): (() => void) => {
        const timeout = setTimeout(() => {
            setUserSearchQuery(userSearchInput.trim());
        }, 300);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [userSearchInput]);

    useEffect((): (() => void) => {
        let isMounted = true;

        const loadUsers = async (): Promise<void> => {
            if (!userPopoverOpen || !canFilterUsers) {
                return;
            }

            setUserLoading(true);
            try {
                const response = await fetchChatUsers(api, {
                    kind,
                    platform: requestPlatform,
                    search: userSearchQuery,
                    limit: 50,
                });

                if (!isMounted) {
                    return;
                }

                setUserOptions(response);
            } catch {
                if (!isMounted) {
                    return;
                }
                setUserOptions([]);
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
    }, [
        api,
        canFilterUsers,
        kind,
        requestPlatform,
        userPopoverOpen,
        userSearchQuery,
    ]);

    useEffect((): (() => void) => {
        let isMounted = true;

        const load = async (): Promise<void> => {
            setLoading(true);
            setError(undefined);
            try {
                const sortKey = sorting[0]?.id ?? "updated_at";
                const descending = sorting[0]?.desc ?? true;
                const userFilterParams = canFilterUsers
                    ? buildUserFilterParams(selectedUser)
                    : {};

                const response = await fetchChatListPage(api, {
                    kind,
                    platform: requestPlatform,
                    search: searchQuery,
                    phraseSearch,
                    userEmail: userFilterParams.userEmail,
                    userGroup: userFilterParams.userGroup,
                    limit: pageSize,
                    offset: pageIndex * pageSize,
                    sortBy: sortKey,
                    descending,
                    timeRange,
                    customRange,
                });

                if (!isMounted) {
                    return;
                }

                setPage(response);
            } catch (error_) {
                if (!isMounted) {
                    return;
                }
                setError(
                    error_ instanceof Error
                        ? error_.message
                        : `Failed to load ${itemNamePlural}`,
                );
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
        customRange,
        itemNamePlural,
        kind,
        pageIndex,
        pageSize,
        platform,
        requestPlatform,
        searchQuery,
        phraseSearch,
        canFilterUsers,
        selectedUser,
        sorting,
        refreshToken,
        timeRange,
    ]);

    useEffect((): (() => void) | undefined => {
        if (!sheetOpen || selectedChatId === undefined) {
            return undefined;
        }

        let active = true;
        const loadDetail = async (): Promise<void> => {
            try {
                const response = await fetchChatDetail(api, selectedChatId, {
                    source:
                        kind === "investigation" ? "investigations" : "chats",
                });
                if (active) {
                    setDetailLoadState({
                        chatId: selectedChatId,
                        detail: response,
                    });
                }
            } catch (error_) {
                if (active) {
                    setDetailLoadState({
                        chatId: selectedChatId,
                        error:
                            error_ instanceof Error && error_.message !== ""
                                ? error_.message
                                : "Failed to load chat",
                    });
                }
            }
        };

        void loadDetail();
        return (): void => {
            active = false;
        };
    }, [api, kind, selectedChatId, sheetOpen]);

    const highlightQuery = highlightMatches ? searchInput.trim() : "";
    const columns = useMemo(
        () =>
            buildColumns(
                highlightQuery,
                phraseSearch,
                showPlatformFilter,
                canViewCost,
                titleColumnHeader,
                kind === "chat",
            ),
        [
            canViewCost,
            highlightQuery,
            kind,
            phraseSearch,
            showPlatformFilter,
            titleColumnHeader,
        ],
    );

    const pageCount = Math.max(1, Math.ceil((page?.total ?? 0) / pageSize));

    const selectedUserLabel =
        selectedUser?.name ?? selectedUser?.email ?? "All users";

    const userOptionsWithOwnerGroups = useMemo(
        () => [...ownerGroupFilterOptions, ...userOptions],
        [ownerGroupFilterOptions, userOptions],
    );

    const orderedUserOptions = useMemo(() => {
        if (platform === "public" || !currentUserOption) {
            return userOptionsWithOwnerGroups;
        }

        const currentIndex = userOptionsWithOwnerGroups.findIndex(
            (option) =>
                option.email === currentUserOption.email &&
                option.platform === currentUserOption.platform,
        );

        if (currentIndex === -1) {
            return userSearchInput.trim() === ""
                ? [currentUserOption, ...userOptionsWithOwnerGroups]
                : userOptionsWithOwnerGroups;
        }

        const filtered = userOptionsWithOwnerGroups.filter(
            (option) =>
                option.email !== currentUserOption.email ||
                option.platform !== currentUserOption.platform,
        );

        return [currentUserOption, ...filtered];
    }, [
        currentUserOption,
        platform,
        userOptionsWithOwnerGroups,
        userSearchInput,
    ]);

    const detailPlatformLabel =
        selectedChat?.isPublic === true ? "Public" : "Internal";
    const detailTitle = selectedChat?.title ?? "Untitled chat";
    const detailUpdatedAt = selectedChat?.updatedAt;
    const sourceConversationId = detail?.investigation_source_conversation_id;
    const sourceMessageId = detail?.investigation_source_message_id;
    const canOpenInvestigatedChat =
        kind === "investigation" &&
        sourceConversationId !== undefined &&
        sourceConversationId !== null;

    useEffect(() => {
        const baseTitle = `${UNIVERSITY_NAME} Enrollment Assistant`;
        setDocumentTitle(
            selectedChat
                ? `${detailTitle} · ${title} · ${baseTitle}`
                : `${title} · ${baseTitle}`,
        );
    }, [detailTitle, selectedChat, title]);
    const selectedIndex = selectedChat
        ? tableData.findIndex((row) => row.id === selectedChat.id)
        : -1;
    const canGoPrev = selectedIndex > 0;
    const canGoNext =
        selectedIndex >= 0 && selectedIndex < tableData.length - 1;

    const resetChatDetail = useCallback((): void => {
        setDetailLoadState(undefined);
    }, []);

    const openTracePanel = (messageId: string): void => {
        setTraceMessageId(messageId);
        setTracePanelOpen(true);
    };

    const openInvestigatedChatInNewTab = useCallback(() => {
        if (
            sourceConversationId === undefined ||
            sourceConversationId === null ||
            sourceConversationId === ""
        ) {
            return;
        }
        openConversationInNewTab({
            conversationId: sourceConversationId,
            messageId: sourceMessageId ?? undefined,
        });
    }, [sourceConversationId, sourceMessageId]);

    const copyTranscript = useCopyChatTranscript(detail);

    const openChatInNewTab = useCallback(() => {
        if (selectedChatId === undefined || selectedChatId === "") {
            return;
        }
        openConversationInNewTab({
            conversationId: selectedChatId,
            target: kind === "investigation" ? "investigation" : "chat",
        });
    }, [kind, selectedChatId]);

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
            highlightPhrase={phraseSearch}
            highlightQuery={highlightQuery}
            loading={activeDetailLoading}
            onDetailChange={(nextDetail) => {
                setDetailLoadState({
                    chatId: nextDetail.id,
                    detail: nextDetail,
                });
            }}
            onFeedbackChange={applyFeedbackChange}
            onOpenTrace={openTracePanel}
            responseLinkTarget={
                kind === "investigation" ? "investigation" : "chat"
            }
            showFeedback={kind === "chat"}
            showInvestigations={kind === "chat"}
            showSummary={showSummary}
            source={kind === "investigation" ? "investigations" : "chats"}
        />
    );

    return (
        <PageShell
            className="overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title={title}>
                {showPlatformFilter && (
                    <PageHeaderGroup>
                        <ToggleGroup
                            aria-label="Platform"
                            onValueChange={(value) => {
                                const [nextValue] = value;
                                const next = isPlatformFilter(nextValue)
                                    ? nextValue
                                    : "both";
                                setPlatform(next);
                                setPageIndex(0);
                            }}
                            value={[platform]}
                            variant="outline"
                        >
                            {platformOptions.map((option) => (
                                <ToggleGroupItem
                                    key={option.value}
                                    value={option.value}
                                >
                                    {option.label}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    </PageHeaderGroup>
                )}
                {canFilterUsers && (
                    <UserFilterPopover
                        label={selectedUserLabel}
                        loading={userLoading}
                        onChange={(option) => {
                            setSelectedUserState(option);
                            setPageIndex(0);
                            setUserPopoverOpen(false);
                        }}
                        onOpenChange={(open) => {
                            setUserPopoverOpen(open);
                            if (open) {
                                setUserSearchInput("");
                                setUserSearchQuery("");
                            }
                        }}
                        onSearchInputChange={setUserSearchInput}
                        open={userPopoverOpen}
                        options={orderedUserOptions}
                        searchInput={userSearchInput}
                    />
                )}
                <PageHeaderGroup>
                    <TimeRangeFilter
                        customRange={customRange}
                        onChange={(value) => {
                            setTimeRange(value);
                            setPageIndex(0);
                        }}
                        onCustomRangeChange={(value) => {
                            setCustomRange(value);
                            setPageIndex(0);
                        }}
                        value={timeRange}
                    />
                </PageHeaderGroup>
                <PageHeaderGroup>
                    <Input
                        className="w-[240px]"
                        onChange={(event) => {
                            setSearchInput(event.target.value);
                        }}
                        placeholder="Search..."
                        value={searchInput}
                    />
                    <div className="flex items-center gap-2">
                        <Switch
                            checked={phraseSearch}
                            id="phrase-search-toggle"
                            onCheckedChange={(checked) => {
                                setPhraseSearch(checked);
                                setPageIndex(0);
                            }}
                        />
                        <Label
                            className="text-muted-foreground"
                            htmlFor="phrase-search-toggle"
                        >
                            Phrase
                        </Label>
                    </div>
                    <div className="flex items-center gap-2">
                        <Switch
                            checked={highlightMatches}
                            id="highlight-search-toggle"
                            onCheckedChange={setHighlightMatches}
                        />
                        <Label
                            className="text-muted-foreground"
                            htmlFor="highlight-search-toggle"
                        >
                            Highlight
                        </Label>
                    </div>
                    <Button
                        onClick={() => {
                            setSearchInput("");
                            setSearchQuery("");
                            setUserSearchInput("");
                            setUserSearchQuery("");
                            setSelectedUserState(undefined);
                            setPhraseSearch(true);
                            setHighlightMatches(true);
                            setPlatform("both");
                            setTimeRange("30d");
                            setCustomRange({});
                            setPageIndex(0);
                        }}
                        variant="outline"
                    >
                        <Filter data-icon="inline-start" />
                        Clear
                    </Button>
                </PageHeaderGroup>
                <Button
                    onClick={() => {
                        setPageIndex(0);
                        setSearchQuery(searchInput.trim());
                        setRefreshToken((value) => value + 1);
                    }}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection className="flex min-h-0 flex-1 flex-col">
                {error !== undefined && <InlineError message={error} />}

                <DataTable
                    columns={columns}
                    data={tableData}
                    emptyMessage={`No ${itemNamePlural} match your filters`}
                    isLoading={loading}
                    isRowSelected={(row) => row.id === selectedChat?.id}
                    manualPagination
                    manualSorting
                    onPaginationChange={(updater) => {
                        if (typeof updater === "function") {
                            const next = updater({
                                pageIndex,
                                pageSize,
                            });
                            setPageIndex(
                                next.pageSize === pageSize ? next.pageIndex : 0,
                            );
                            setPageSize(next.pageSize);
                        } else {
                            setPageIndex(
                                updater.pageSize === pageSize
                                    ? updater.pageIndex
                                    : 0,
                            );
                            setPageSize(updater.pageSize);
                        }
                    }}
                    onRowClick={(chat) => {
                        resetChatDetail();
                        void navigate({
                            search: (prev) => ({
                                ...prev,
                                chat: chat.id,
                            }),
                            to: routePath,
                        });
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
                        setDetailLoadState(undefined);
                        setTracePanelOpen(false);
                        setTraceMessageId(undefined);
                        void navigate({
                            search: (prev) => ({
                                ...prev,
                                chat: undefined,
                            }),
                            to: routePath,
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
                            <div className="flex flex-wrap items-center justify-end gap-2">
                                {canOpenInvestigatedChat && (
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger
                                                render={
                                                    <Button
                                                        aria-label="Open investigated chat in new tab"
                                                        onClick={
                                                            openInvestigatedChatInNewTab
                                                        }
                                                        size="icon-sm"
                                                        type="button"
                                                        variant="ghost"
                                                    >
                                                        <ExternalLink />
                                                    </Button>
                                                }
                                            />
                                            <TooltipContent>
                                                Open investigated chat in new
                                                tab
                                            </TooltipContent>
                                        </Tooltip>
                                    </TooltipProvider>
                                )}
                                <ChatReviewSheetActions
                                    canGoNext={canGoNext}
                                    canGoPrev={canGoPrev}
                                    copyDisabled={detail === undefined}
                                    nextLabel={`Next ${itemName}`}
                                    onCopyTranscript={() => {
                                        void copyTranscript();
                                    }}
                                    onGoNext={() => {
                                        if (!canGoNext) {
                                            return;
                                        }
                                        const next =
                                            tableData[selectedIndex + 1];
                                        resetChatDetail();
                                        void navigate({
                                            search: (prev) => ({
                                                ...prev,
                                                chat: next.id,
                                            }),
                                            to: routePath,
                                        });
                                    }}
                                    onGoPrev={() => {
                                        if (!canGoPrev) {
                                            return;
                                        }
                                        const previous =
                                            tableData[selectedIndex - 1];
                                        resetChatDetail();
                                        void navigate({
                                            search: (prev) => ({
                                                ...prev,
                                                chat: previous.id,
                                            }),
                                            to: routePath,
                                        });
                                    }}
                                    onOpenChat={openChatInNewTab}
                                    onShowSummaryChange={setShowSummary}
                                    openChatDisabled={
                                        selectedChatId === undefined ||
                                        selectedChatId === ""
                                    }
                                    openChatTooltip="Open in new tab"
                                    previousLabel={`Previous ${itemName}`}
                                    showSummary={showSummary}
                                    summaryToggleId="summary-toggle"
                                />
                            </div>
                        </div>
                        <SheetDescription>
                            {selectedChat !== undefined &&
                            detailUpdatedAt !== undefined ? (
                                <span className="inline-flex flex-wrap items-center gap-2">
                                    <Badge
                                        variant={
                                            selectedChat.isPublic
                                                ? "secondary"
                                                : "outline"
                                        }
                                    >
                                        {detailPlatformLabel}
                                    </Badge>
                                    {selectedChat.promptSource === "draft" && (
                                        <Badge variant="secondary">
                                            Draft instructions
                                        </Badge>
                                    )}
                                    <span>
                                        Updated{" "}
                                        {formatTimestamp(detailUpdatedAt)}
                                    </span>
                                </span>
                            ) : (
                                `${titleColumnHeader} details`
                            )}
                        </SheetDescription>
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

export const ChatsPage = (): JSX.Element => <ChatReviewListPage />;

export const InvestigationsPage = (): JSX.Element => (
    <ChatReviewListPage
        kind="investigation"
        routePath="/investigations"
        title="Investigations"
    />
);

interface StandaloneChatDetailPageProps {
    chatId: string;
    focusMessageId?: string;
    kind: ReviewCollectionKind;
}

const StandaloneChatDetailPage = ({
    chatId,
    focusMessageId,
    kind,
}: StandaloneChatDetailPageProps): JSX.Element => {
    const api = useAuthenticatedApi();
    const detailRequests = useMemo(() => createLatestRequestCoordinator(), []);
    const { user } = useAuth();
    const canViewTrace = hasPermission(user, "chats_view_trace");
    const canViewDurationTooltip = hasPermission(user, "chat_duration_tooltip");
    const canViewResponseCost = hasPermission(user, "chat_view_response_cost");
    const canViewGuardrailsFailures = hasPermission(
        user,
        "chat_view_guardrails_failures",
    );
    const canViewSources = hasPermission(user, "chat_view_sources");
    const canViewTools = hasPermission(user, "chat_view_tools");
    const [detail, setDetail] = useState<ChatDetailResponse | undefined>();
    const [detailLoading, setDetailLoading] = useState(true);
    const [detailError, setDetailError] = useState<string | undefined>();
    const [showSummary, setShowSummary] = usePersistentChatSummary(
        "internal-chat-summary-open",
    );
    const [tracePanelOpen, setTracePanelOpen] = useState(false);
    const [traceMessageId, setTraceMessageId] = useState<string | undefined>();
    const itemLabel = kind === "investigation" ? "investigation" : "chat";
    const itemLabelTitle = kind === "investigation" ? "Investigation" : "Chat";
    const responseLinkTarget: ResponseLinkTarget =
        kind === "investigation" ? "investigation" : "chat";

    const requestDetail = useCallback(
        async () =>
            detailRequests.run(async () =>
                fetchChatDetail(api, chatId, {
                    source:
                        kind === "investigation" ? "investigations" : "chats",
                    targetMessageId: focusMessageId,
                }),
            ),
        [api, chatId, detailRequests, focusMessageId, kind],
    );
    const startDetailRequest = useCallback((): void => {
        void requestDetail().then(
            (result) => {
                if (result.status === "current") {
                    setDetail(result.value);
                    setDetailLoading(false);
                }
            },
            (error: unknown) => {
                setDetailError(
                    error instanceof Error
                        ? error.message
                        : `Failed to load ${itemLabel}`,
                );
                setDetailLoading(false);
            },
        );
    }, [itemLabel, requestDetail]);
    const loadDetail = useCallback((): void => {
        setDetailLoading(true);
        setDetailError(undefined);
        startDetailRequest();
    }, [startDetailRequest]);

    useEffect(() => {
        startDetailRequest();
        return (): void => {
            detailRequests.invalidate();
        };
    }, [detailRequests, startDetailRequest]);

    const title =
        detail?.title ??
        (kind === "investigation" ? "Untitled investigation" : "Untitled chat");
    const ownerName = detail?.user_name?.trim();
    const ownerEmail = detail?.user_email?.trim();
    const ownerLabel =
        ownerName !== undefined && ownerName !== ""
            ? ownerName
            : ownerEmail !== undefined && ownerEmail !== ""
              ? ownerEmail
              : "Unknown user";
    const showOwnerEmail =
        ownerEmail !== undefined && ownerEmail !== ownerLabel;
    const sourceConversationId =
        detail?.investigation_source_conversation_id ?? undefined;
    const sourceMessageId =
        detail?.investigation_source_message_id ?? undefined;
    const canOpenInvestigatedChat =
        kind === "investigation" && sourceConversationId !== undefined;

    const copyTranscript = useCopyChatTranscript(detail);

    const openTracePanel = useCallback((messageId: string): void => {
        setTraceMessageId(messageId);
        setTracePanelOpen(true);
    }, []);

    const openInvestigatedChatInNewTab = useCallback((): void => {
        if (sourceConversationId === undefined) {
            return;
        }
        openConversationInNewTab({
            conversationId: sourceConversationId,
            messageId: sourceMessageId,
        });
    }, [sourceConversationId, sourceMessageId]);

    const ignoreFeedbackChange = (): void => undefined;

    return (
        <PageShell
            className="overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title={title}>
                <PageHeaderGroup>
                    <Label
                        className="text-muted-foreground"
                        htmlFor="single-chat-summary-toggle"
                    >
                        Summary
                    </Label>
                    <Switch
                        checked={showSummary}
                        id="single-chat-summary-toggle"
                        onCheckedChange={setShowSummary}
                    />
                </PageHeaderGroup>
                {canOpenInvestigatedChat && (
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        aria-label="Open investigated chat in new tab"
                                        onClick={openInvestigatedChatInNewTab}
                                        size="icon"
                                        type="button"
                                        variant="ghost"
                                    >
                                        <ExternalLink />
                                    </Button>
                                }
                            />
                            <TooltipContent>
                                Open investigated chat in new tab
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                )}
                <Button
                    disabled={detail === undefined}
                    onClick={() => {
                        void copyTranscript();
                    }}
                    variant="outline"
                >
                    <Copy data-icon="inline-start" />
                    Copy transcript
                </Button>
                <Button
                    onClick={loadDetail}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection className="flex min-h-0 flex-1 flex-col gap-4">
                <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
                    {detail === undefined ? (
                        `${itemLabelTitle} ${chatId}`
                    ) : (
                        <>
                            <span>
                                Updated {formatTimestamp(detail.updated_at)}
                            </span>
                            <span aria-hidden="true">·</span>
                            <span>{ownerLabel}</span>
                            {showOwnerEmail && (
                                <span>&lt;{ownerEmail}&gt;</span>
                            )}
                            <Badge
                                variant={
                                    detail.is_public ? "secondary" : "outline"
                                }
                            >
                                {detail.is_public ? "Public" : "Internal"}
                            </Badge>
                            {detail.prompt_source === "draft" && (
                                <Badge variant="secondary">
                                    Draft instructions
                                </Badge>
                            )}
                        </>
                    )}
                </div>
                <div className="min-h-0 flex-1 overflow-hidden">
                    <ChatDetailContent
                        canViewDurationTooltip={canViewDurationTooltip}
                        canViewGuardrailsFailures={canViewGuardrailsFailures}
                        canViewResponseCost={canViewResponseCost}
                        canViewSources={canViewSources}
                        canViewTools={canViewTools}
                        canViewTrace={canViewTrace}
                        detail={detail}
                        error={detailError}
                        focusMessageId={focusMessageId}
                        highlightPhrase={false}
                        highlightQuery=""
                        loading={detailLoading}
                        onDetailChange={setDetail}
                        onFeedbackChange={ignoreFeedbackChange}
                        onOpenTrace={openTracePanel}
                        responseLinkTarget={responseLinkTarget}
                        showFeedback={kind === "chat"}
                        showInvestigations={kind === "chat"}
                        showSummary={showSummary}
                        source={
                            kind === "investigation"
                                ? "investigations"
                                : "chats"
                        }
                    />
                </div>
            </PageSection>

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

export const ChatDetailPage = (): JSX.Element => {
    const { chatId } = useParams({ from: "/chats/$chatId" });
    const { message: focusMessageId } = useSearch({ from: "/chats/$chatId" });

    return (
        <StandaloneChatDetailPage
            chatId={chatId}
            focusMessageId={focusMessageId}
            key={`${chatId}:${focusMessageId ?? ""}`}
            kind="chat"
        />
    );
};

export const InvestigationDetailPage = (): JSX.Element => {
    const { chatId } = useParams({ from: "/investigations/$chatId" });
    const { message: focusMessageId } = useSearch({
        from: "/investigations/$chatId",
    });

    return (
        <StandaloneChatDetailPage
            chatId={chatId}
            focusMessageId={focusMessageId}
            key={`${chatId}:${focusMessageId ?? ""}`}
            kind="investigation"
        />
    );
};
