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
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@va/shared/components/ui/command";
import { Input } from "@va/shared/components/ui/input";
import { Label } from "@va/shared/components/ui/label";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@va/shared/components/ui/popover";
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
    ChevronsUpDown,
    Copy,
    ExternalLink,
    Filter,
    Link,
    ListTree,
    RefreshCw,
    ThumbsDown,
    ThumbsUp,
    UserRound,
} from "lucide-react";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable } from "@/components/data-table";
import { getDefaultDataTablePageSize } from "@/components/data-table-constants";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
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
import { fetchChatDetail } from "../../chat/lib/api";
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
import { formatTableTimestamp } from "../../lib/date-format";
import { formatLocaleNumber } from "../../lib/number-format";
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
    getUserOptionPrimaryLabel,
    getUserOptionSecondaryLabel,
} from "../lib/user-filter-options";
import type {
    ChatListPage as ChatListPageResponse,
    ChatListRow,
    ChatUserOption,
} from "../types";
import { ChatReviewSheetActions } from "./chat-review-sheet-actions";
import { ChatTurnTraceSheet } from "./chat-turn-trace-sheet";

const formatCost = (cost: number | undefined): string => {
    if (cost === undefined) {
        return "-";
    }
    if (cost === 0) {
        return "$0.00";
    }
    return cost < 0.01
        ? `$${formatLocaleNumber(cost, {
              minimumFractionDigits: 4,
              maximumFractionDigits: 4,
          })}`
        : `$${formatLocaleNumber(cost, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
          })}`;
};

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
                        <div className="truncate text-sm font-semibold">
                            <HighlightedText
                                phrase={phrase}
                                query={query}
                                text={title}
                            />
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
        {
            id: "message_count",
            accessorKey: "messageCount",
            header: "Messages",
            enableSorting: true,
            meta: {
                skeleton: skeletonLine("h-4 w-12"),
            },
            cell: ({ row }): JSX.Element => (
                <div className="tabular-nums">
                    {formatLocaleNumber(row.original.messageCount)}
                </div>
            ),
        },
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

    if (showPlatformColumn) {
        columns.splice(2, 0, {
            id: "platform",
            header: "Platform",
            meta: {
                skeleton: skeletonLine("h-6 w-20 rounded-full"),
            },
            cell: ({ row }): JSX.Element => (
                <Badge
                    variant={row.original.isPublic ? "secondary" : "outline"}
                >
                    {row.original.isPublic ? "Public" : "Internal"}
                </Badge>
            ),
        });
    }

    if (canViewCost) {
        columns.splice(showPlatformColumn ? 4 : 3, 0, {
            id: "total_cost",
            accessorKey: "totalCost",
            header: "Cost",
            enableSorting: true,
            meta: {
                skeleton: skeletonLine("h-4 w-16"),
            },
            cell: ({ row }): JSX.Element => (
                <div className="tabular-nums">
                    {formatCost(row.original.totalCost)}
                </div>
            ),
        });
    }

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
    parentId: message.parent_id,
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
    selectedUser?: {
        email: string;
        name?: string;
        ownerGroup?: ChatUserOption["ownerGroup"];
        platform: ChatUserOption["platform"];
    };
}

const isPlatformFilter = (value: string): value is PlatformFilter =>
    platformOptions.some((option) => option.value === value);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

const isChatPlatform = (value: string): value is ChatUserOption["platform"] =>
    value === "internal" || value === "public";

const isOwnerGroup = (
    value: string,
): value is NonNullable<ChatUserOption["ownerGroup"]> =>
    value === "staff" || value === "devs";

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
        const selectedUserValue = isRecord(parsed.selectedUser)
            ? parsed.selectedUser
            : undefined;
        const selectedUserEmail =
            typeof selectedUserValue?.email === "string"
                ? selectedUserValue.email
                : undefined;
        const selectedUserPlatform =
            typeof selectedUserValue?.platform === "string" &&
            isChatPlatform(selectedUserValue.platform)
                ? selectedUserValue.platform
                : undefined;
        const selectedUserOwnerGroup =
            typeof selectedUserValue?.ownerGroup === "string" &&
            isOwnerGroup(selectedUserValue.ownerGroup)
                ? selectedUserValue.ownerGroup
                : undefined;
        const hasSelectedUser =
            selectedUserEmail !== undefined &&
            selectedUserEmail !== "" &&
            selectedUserPlatform !== undefined;
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
            selectedUser: hasSelectedUser
                ? {
                      email: selectedUserEmail,
                      name:
                          typeof selectedUserValue?.name === "string"
                              ? selectedUserValue.name
                              : undefined,
                      ownerGroup: selectedUserOwnerGroup,
                      platform: selectedUserPlatform,
                  }
                : undefined,
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

const getStoredSelectedUser = (
    value: StoredChatFilters["selectedUser"] | undefined,
): ChatUserOption | undefined => {
    if (value?.email === undefined || value.email === "") {
        return undefined;
    }
    return {
        email: value.email,
        name: value.name,
        ownerGroup: value.ownerGroup,
        platform: value.platform,
    };
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
    onFeedbackChange: (change: FeedbackChange) => void;
    onOpenTrace: (messageId: string) => void;
    responseLinkTarget?: ResponseLinkTarget;
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
    onFeedbackChange,
    onOpenTrace,
    responseLinkTarget = "chat",
    showFeedback = true,
    showInvestigations = true,
    showSummary,
}: ChatDetailContentProps): JSX.Element => {
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

    const chatPanel = (
        <ChatStoreProvider>
            {showFeedback && <DetailFeedbackInitializer detail={detail} />}
            <Chat
                autoScroll={false}
                canSendMessages={false}
                contentWidthMode="standard"
                disableVoiceFeatures
                focusMessageId={focusMessageId}
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
                        sourceButtons === undefined
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
    const [selectedUser, setSelectedUser] = useState<
        ChatUserOption | undefined
    >(() => getStoredSelectedUser(storedFilters?.selectedUser));
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
        [canViewCurrentUserChats, user?.email, user?.name],
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

    const [sheetOpen, setSheetOpen] = useState(false);
    const [selectedChat, setSelectedChat] = useState<ChatListRow | undefined>();
    const [detail, setDetail] = useState<ChatDetailResponse | undefined>();
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | undefined>();
    const [tracePanelOpen, setTracePanelOpen] = useState(false);
    const [traceMessageId, setTraceMessageId] = useState<string | undefined>();
    const requestPlatform =
        kind === "investigation"
            ? "internal"
            : platform === "both"
              ? undefined
              : platform;

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

            setSelectedChat((prev) => {
                if (prev?.id !== selectedChat.id) {
                    return prev;
                }
                return {
                    ...prev,
                    feedbackUp: Math.max(0, prev.feedbackUp + deltaUp),
                    feedbackDown: Math.max(0, prev.feedbackDown + deltaDown),
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

    useEffect(() => {
        if (canFilterUsers || selectedUser === undefined) {
            return (): void => undefined;
        }

        const timeout = setTimeout(() => {
            setSelectedUser(undefined);
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [canFilterUsers, selectedUser]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            setPageIndex(0);
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [
        customRange,
        platform,
        pageSize,
        sorting,
        timeRange,
        selectedUser,
        phraseSearch,
    ]);

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

    const selectedChatId = selectedChat?.id;

    useEffect((): (() => void) | undefined => {
        if (!sheetOpen || selectedChatId === undefined) {
            return undefined;
        }

        let isMounted = true;

        const loadDetail = async (): Promise<void> => {
            setDetailLoading(true);
            setDetailError(undefined);
            try {
                const response = await fetchChatDetail(api, selectedChatId, {
                    source:
                        kind === "investigation" ? "investigations" : "chats",
                });
                if (!isMounted) {
                    return;
                }
                setDetail(response);
            } catch (error_) {
                if (!isMounted) {
                    return;
                }
                setDetailError(
                    error_ instanceof Error
                        ? error_.message
                        : "Failed to load chat",
                );
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

    const tableData = useMemo(() => page?.items ?? [], [page]);
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

    const openChat = (chat: ChatListRow): void => {
        setSelectedChat(chat);
        setDetail(undefined);
        setDetailError(undefined);
        setDetailLoading(true);
        setSheetOpen(true);
    };

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

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (search.chat === undefined) {
                if (sheetOpen) {
                    setSheetOpen(false);
                }
                setSelectedChat(undefined);
                return;
            }

            if (selectedChat?.id === search.chat) {
                if (!sheetOpen) {
                    setSheetOpen(true);
                }
                return;
            }

            const match = tableData.find((row) => row.id === search.chat);
            if (match) {
                openChat(match);
            } else {
                setSelectedChat(undefined);
                setSheetOpen(false);
            }
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [search.chat, selectedChat, sheetOpen, tableData]);

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
            loading={detailLoading}
            onFeedbackChange={applyFeedbackChange}
            onOpenTrace={openTracePanel}
            responseLinkTarget={
                kind === "investigation" ? "investigation" : "chat"
            }
            showFeedback={kind === "chat"}
            showInvestigations={kind === "chat"}
            showSummary={showSummary}
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
                    <PageHeaderGroup>
                        <Popover
                            onOpenChange={(open) => {
                                setUserPopoverOpen(open);
                                if (open) {
                                    setUserSearchInput("");
                                    setUserSearchQuery("");
                                }
                            }}
                            open={userPopoverOpen}
                        >
                            <PopoverTrigger
                                render={
                                    <Button
                                        className="w-[240px] justify-between gap-2"
                                        variant="outline"
                                    >
                                        <span className="flex min-w-0 items-center gap-2">
                                            <UserRound className="text-muted-foreground" />
                                            <span className="truncate">
                                                {selectedUserLabel}
                                            </span>
                                        </span>
                                        <ChevronsUpDown className="text-muted-foreground" />
                                    </Button>
                                }
                            />
                            <PopoverContent
                                align="start"
                                className="w-[320px] p-0"
                            >
                                <Command shouldFilter={false}>
                                    <CommandInput
                                        onValueChange={setUserSearchInput}
                                        placeholder="Search users..."
                                        value={userSearchInput}
                                    />
                                    <CommandList>
                                        <CommandEmpty>
                                            {userLoading
                                                ? "Loading users..."
                                                : "No users found"}
                                        </CommandEmpty>
                                        <CommandGroup>
                                            {userSearchInput === "" && (
                                                <CommandItem
                                                    onSelect={() => {
                                                        setSelectedUser(
                                                            undefined,
                                                        );
                                                        setUserPopoverOpen(
                                                            false,
                                                        );
                                                    }}
                                                >
                                                    All users
                                                </CommandItem>
                                            )}
                                            {orderedUserOptions.map((user) => (
                                                <CommandItem
                                                    key={`${user.platform}-${user.email}`}
                                                    onSelect={() => {
                                                        setSelectedUser(user);
                                                        setUserPopoverOpen(
                                                            false,
                                                        );
                                                    }}
                                                    value={user.email}
                                                >
                                                    <div className="flex min-w-0 flex-1 flex-col">
                                                        <span className="truncate text-sm">
                                                            {getUserOptionPrimaryLabel(
                                                                user,
                                                            )}
                                                        </span>
                                                        {getUserOptionSecondaryLabel(
                                                            user,
                                                        ) !== undefined && (
                                                            <span className="text-muted-foreground truncate text-xs">
                                                                {getUserOptionSecondaryLabel(
                                                                    user,
                                                                )}
                                                            </span>
                                                        )}
                                                    </div>
                                                    <Badge
                                                        variant={
                                                            user.platform ===
                                                            "public"
                                                                ? "secondary"
                                                                : "outline"
                                                        }
                                                    >
                                                        {user.platform ===
                                                        "public"
                                                            ? "Public"
                                                            : "Internal"}
                                                    </Badge>
                                                </CommandItem>
                                            ))}
                                        </CommandGroup>
                                    </CommandList>
                                </Command>
                            </PopoverContent>
                        </Popover>
                    </PageHeaderGroup>
                )}
                <PageHeaderGroup>
                    <TimeRangeFilter
                        customRange={customRange}
                        onChange={setTimeRange}
                        onCustomRangeChange={setCustomRange}
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
                            onCheckedChange={setPhraseSearch}
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
                            setSelectedUser(undefined);
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
                            setPageIndex(next.pageIndex);
                            setPageSize(next.pageSize);
                        } else {
                            setPageIndex(updater.pageIndex);
                            setPageSize(updater.pageSize);
                        }
                    }}
                    onRowClick={(chat) => {
                        openChat(chat);
                        void navigate({
                            search: (prev) => ({
                                ...prev,
                                chat: chat.id,
                            }),
                            to: routePath,
                        });
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
                        setSelectedChat(undefined);
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
                                        openChat(next);
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
                                        openChat(previous);
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

    const loadDetail = useCallback(async (): Promise<void> => {
        setDetailLoading(true);
        setDetailError(undefined);
        try {
            const response = await fetchChatDetail(api, chatId, {
                source: kind === "investigation" ? "investigations" : "chats",
                targetMessageId: focusMessageId,
            });
            setDetail(response);
        } catch (error_) {
            setDetailError(
                error_ instanceof Error
                    ? error_.message
                    : `Failed to load ${itemLabel}`,
            );
        } finally {
            setDetailLoading(false);
        }
    }, [api, chatId, focusMessageId, itemLabel, kind]);

    useEffect(() => {
        void loadDetail();
    }, [loadDetail]);

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
                    onClick={() => void loadDetail()}
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
                        onFeedbackChange={ignoreFeedbackChange}
                        onOpenTrace={openTracePanel}
                        responseLinkTarget={responseLinkTarget}
                        showFeedback={kind === "chat"}
                        showInvestigations={kind === "chat"}
                        showSummary={showSummary}
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
            kind="investigation"
        />
    );
};
