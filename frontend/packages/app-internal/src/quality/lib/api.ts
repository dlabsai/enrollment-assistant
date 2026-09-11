import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { QualityPlatform, QualitySummary } from "../types";

export interface FetchedQualitySummary {
    appliedRange: {
        start?: string;
        end?: string;
        timeRange: "all" | "custom";
    };
    summary: QualitySummary;
}

export const fetchQualitySummary = async (
    api: Pick<AuthenticatedApi, "get">,
    platform: QualityPlatform,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    userEmail?: string,
    userGroup?: "staff" | "devs",
    signal?: AbortSignal,
): Promise<FetchedQualitySummary> => {
    const range = getTimeRangeQueryParams(timeRange, new Date(), customRange);
    const params = new URLSearchParams(range);
    if (platform !== "both") {
        params.set("platform", platform);
    }
    if (userEmail !== undefined && userEmail !== "") {
        params.set("user_email", userEmail);
    }
    if (userGroup !== undefined) {
        params.set("user_group", userGroup);
    }
    const summary = await api.get<QualitySummary>(
        `/analytics/quality?${params.toString()}`,
        { signal },
    );
    return {
        appliedRange: {
            ...range,
            timeRange: range.start === undefined ? "all" : "custom",
        },
        summary,
    };
};
