import { parseRouteDateRange } from "./review-search-state";

export interface ChatsSearch {
    chat?: string;
    minTurns?: number;
    maxTurns?: number;
    platform?: "internal" | "public";
    analyticsStart?: string;
    analyticsEnd?: string;
    analyticsEndBefore?: string;
    userEmail?: string;
    userGroup?: "staff" | "devs";
}

const parseNonnegativeInteger = (value: unknown): number | undefined => {
    const parsed =
        typeof value === "number"
            ? value
            : typeof value === "string" && value.trim() !== ""
              ? Number(value)
              : Number.NaN;
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : undefined;
};

export const validateChatsSearch = (
    search: Record<string, unknown>,
): ChatsSearch => {
    const parsedMinTurns = parseNonnegativeInteger(search.minTurns);
    const maxTurnsWasProvided = search.maxTurns !== undefined;
    const parsedMaxTurns = parseNonnegativeInteger(search.maxTurns);
    const validTurnBounds =
        parsedMinTurns !== undefined &&
        (!maxTurnsWasProvided ||
            (parsedMaxTurns !== undefined && parsedMaxTurns >= parsedMinTurns));
    const range = parseRouteDateRange(
        search.analyticsStart,
        search.analyticsEnd,
        search.analyticsEndBefore,
    );
    const creationOnly =
        search.minTurns === undefined &&
        search.maxTurns === undefined &&
        (range?.start !== undefined ||
            range?.end !== undefined ||
            range?.endBefore !== undefined);
    const validAnalyticsDrilldown =
        range !== undefined && (validTurnBounds || creationOnly);

    return {
        chat: typeof search.chat === "string" ? search.chat : undefined,
        minTurns: validAnalyticsDrilldown ? parsedMinTurns : undefined,
        maxTurns: validAnalyticsDrilldown ? parsedMaxTurns : undefined,
        platform:
            validAnalyticsDrilldown &&
            (search.platform === "internal" || search.platform === "public")
                ? search.platform
                : undefined,
        analyticsStart: validAnalyticsDrilldown ? range.start : undefined,
        analyticsEnd: validAnalyticsDrilldown ? range.end : undefined,
        analyticsEndBefore: validAnalyticsDrilldown
            ? range.endBefore
            : undefined,
        userEmail:
            validAnalyticsDrilldown && typeof search.userEmail === "string"
                ? search.userEmail
                : undefined,
        userGroup:
            validAnalyticsDrilldown &&
            (search.userGroup === "staff" || search.userGroup === "devs")
                ? search.userGroup
                : undefined,
    };
};
