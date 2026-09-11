import { parseRouteDateRange } from "../../chats/lib/review-search-state";
import { isTimeRangeValue, type TimeRangeValue } from "../../lib/time-range";

export type MessageRoleFilter = "assistant" | "user" | "all";
export type MessagePlatformFilter = "all" | "internal" | "public";
export type GuardrailStatusFilter = "all" | "retried" | "blocked";

export interface MessagesSearch {
    excludeDraft?: boolean;
    guardrailStatus?: GuardrailStatusFilter;
    minGenerationTimeMs?: number;
    maxGenerationTimeMs?: number;
    platform?: Exclude<MessagePlatformFilter, "all">;
    role?: MessageRoleFilter;
    search?: string;
    sortBy?: string;
    descending?: boolean;
    start?: string;
    end?: string;
    endBefore?: string;
    conversationStart?: string;
    conversationEnd?: string;
    timeRange?: TimeRangeValue;
    userEmail?: string;
    userGroup?: "staff" | "devs";
}

const messageSortKeys = new Set([
    "content_length",
    "created_at",
    "updated_at",
    "role",
    "conversation_title",
    "generation_time_ms",
    "uncached_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
    "response_cost",
    "tool_call_count",
    "guardrail_failure_count",
    "guardrail_retry_count",
    "guardrails_blocked",
]);

const parseNonnegativeNumber = (value: unknown): number | undefined => {
    const parsed =
        typeof value === "number"
            ? value
            : typeof value === "string" && value.trim() !== ""
              ? Number(value)
              : Number.NaN;
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
};

export const validateMessagesSearch = (
    search: Record<string, unknown>,
): MessagesSearch => {
    const conversationRange = parseRouteDateRange(
        search.conversationStart,
        search.conversationEnd,
    );
    const range = parseRouteDateRange(
        search.start,
        search.end,
        search.endBefore,
    );
    return {
        conversationStart: conversationRange?.start,
        conversationEnd: conversationRange?.end,
        excludeDraft:
            search.excludeDraft === true || search.excludeDraft === "true"
                ? true
                : undefined,
        guardrailStatus:
            search.guardrailStatus === "retried" ||
            search.guardrailStatus === "blocked" ||
            search.guardrailStatus === "all"
                ? search.guardrailStatus
                : undefined,
        minGenerationTimeMs: parseNonnegativeNumber(search.minGenerationTimeMs),
        maxGenerationTimeMs: parseNonnegativeNumber(search.maxGenerationTimeMs),
        platform:
            search.platform === "internal" || search.platform === "public"
                ? search.platform
                : undefined,
        role:
            search.role === "assistant" ||
            search.role === "user" ||
            search.role === "all"
                ? search.role
                : undefined,
        search: typeof search.search === "string" ? search.search : undefined,
        sortBy:
            typeof search.sortBy === "string" &&
            messageSortKeys.has(search.sortBy)
                ? search.sortBy
                : undefined,
        descending:
            search.descending === true || search.descending === "true"
                ? true
                : search.descending === false || search.descending === "false"
                  ? false
                  : undefined,
        start: range?.start,
        end: range?.end,
        endBefore: range?.endBefore,
        timeRange:
            typeof search.timeRange === "string" &&
            isTimeRangeValue(search.timeRange)
                ? search.timeRange
                : undefined,
        userEmail:
            typeof search.userEmail === "string" ? search.userEmail : undefined,
        userGroup:
            search.userGroup === "staff" || search.userGroup === "devs"
                ? search.userGroup
                : undefined,
    };
};
