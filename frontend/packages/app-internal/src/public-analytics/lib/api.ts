import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { PublicUsageSummary } from "../../usage/types";

export const fetchPublicUsageSummary = async (
    api: AuthenticatedApi,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    signal?: AbortSignal,
): Promise<PublicUsageSummary> => {
    const params = new URLSearchParams(
        getTimeRangeQueryParams(timeRange, new Date(), customRange),
    );
    const query = params.toString();
    return api.get<PublicUsageSummary>(
        query ? `/analytics/public-usage?${query}` : "/analytics/public-usage",
        { signal },
    );
};
