import { parseRouteDateRange } from "../../chats/lib/review-search-state";
import { isTimeRangeValue, type TimeRangeValue } from "../../lib/time-range";

export type FeedbackRatingFilter = "thumbs_up" | "thumbs_down" | "all";
export type FeedbackPlatformFilter = "all" | "internal" | "public";

export interface FeedbackSearch {
    chat?: string;
    excludeDraft?: boolean;
    message?: string;
    platform?: Exclude<FeedbackPlatformFilter, "all">;
    rating?: Exclude<FeedbackRatingFilter, "all">;
    search?: string;
    start?: string;
    end?: string;
    endBefore?: string;
    timeRange?: TimeRangeValue;
    userEmail?: string;
    userGroup?: "staff" | "devs";
}

export const validateFeedbackSearch = (
    search: Record<string, unknown>,
): FeedbackSearch => ({
    chat: typeof search.chat === "string" ? search.chat : undefined,
    excludeDraft:
        search.excludeDraft === true || search.excludeDraft === "true"
            ? true
            : undefined,
    message: typeof search.message === "string" ? search.message : undefined,
    platform:
        search.platform === "internal" || search.platform === "public"
            ? search.platform
            : undefined,
    rating:
        search.rating === "thumbs_up" || search.rating === "thumbs_down"
            ? search.rating
            : undefined,
    search: typeof search.search === "string" ? search.search : undefined,
    ...parseRouteDateRange(search.start, search.end, search.endBefore),
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
});
