import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { UsageOverviewApi } from "../types";

export type UsagePlatformFilter = "both" | "internal" | "public";

interface UsageOverviewParams {
    platform: UsagePlatformFilter;
    timeRange: TimeRangeValue;
    customRange: CustomTimeRange;
    modelFilters?: string[];
    userEmail?: string;
    userGroup?: "staff" | "devs";
    referenceDate?: Date;
    signal?: AbortSignal;
}

export const fetchUsageOverview = async (
    api: AuthenticatedApi,
    {
        platform,
        timeRange,
        customRange,
        modelFilters,
        userEmail,
        userGroup,
        referenceDate,
        signal,
    }: UsageOverviewParams,
): Promise<UsageOverviewApi> => {
    const params = new URLSearchParams(
        getTimeRangeQueryParams(timeRange, referenceDate, customRange),
    );

    if (platform !== "both") {
        params.set("platform", platform);
    }

    if (modelFilters !== undefined && modelFilters.length > 0) {
        for (const modelFilter of modelFilters) {
            params.append("models", modelFilter);
        }
    }
    if (userEmail !== undefined && userEmail !== "") {
        params.set("user_email", userEmail);
    }
    if (userGroup !== undefined) {
        params.set("user_group", userGroup);
    }

    const query = params.toString();
    return api.get<UsageOverviewApi>(
        query ? `/usage/summary?${query}` : "/usage/summary",
        { signal },
    );
};
