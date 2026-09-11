import type { ChatsSearch } from "../../chats/lib/search-state";
import { getTimeSeriesBucketRange } from "../../lib/time-series";
import type { MessagesSearch } from "../../messages/lib/search-state";
import type {
    ChatAnalyticsBucket,
    ChatAnalyticsTimeSeriesPoint,
} from "../types";
import type { ChatAnalyticsPlatform, FetchedChatAnalyticsSummary } from "./api";

export const getChatVolumeDrilldownSearch = (
    point: ChatAnalyticsTimeSeriesPoint,
    platform: ChatAnalyticsPlatform,
    owner: Pick<ChatsSearch, "userEmail" | "userGroup">,
): ChatsSearch => {
    const range = getTimeSeriesBucketRange(point);
    return {
        analyticsStart: range.start,
        analyticsEndBefore: range.endBefore,
        platform: platform === "both" ? undefined : platform,
        ...owner,
    };
};

export const getTurnsVolumeDrilldownSearch = (
    point: ChatAnalyticsTimeSeriesPoint,
    appliedRange: FetchedChatAnalyticsSummary["appliedRange"],
    platform: ChatAnalyticsPlatform,
    owner: Pick<ChatsSearch, "userEmail" | "userGroup">,
): MessagesSearch => ({
    ...getTimeSeriesBucketRange(point),
    conversationStart: appliedRange.start,
    conversationEnd: appliedRange.end,
    role: "user",
    platform: platform === "both" ? undefined : platform,
    ...owner,
});

export const getChatLengthDrilldownSearch = (
    bucket: ChatAnalyticsBucket,
    appliedRange: FetchedChatAnalyticsSummary["appliedRange"],
    platform: ChatAnalyticsPlatform,
    owner: Pick<ChatsSearch, "userEmail" | "userGroup">,
): ChatsSearch => ({
    chat: undefined,
    minTurns: bucket.min_turns,
    maxTurns: bucket.max_turns ?? undefined,
    platform: platform === "both" ? undefined : platform,
    analyticsStart: appliedRange.start,
    analyticsEnd: appliedRange.end,
    userEmail: owner.userEmail,
    userGroup: owner.userGroup,
});
