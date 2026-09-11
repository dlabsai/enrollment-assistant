import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { PublicAnalyticsSummary } from "../types";

export const fetchPublicAnalyticsSummary = async (
    api: AuthenticatedApi,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    signal?: AbortSignal,
): Promise<PublicAnalyticsSummary> => {
    const params = new URLSearchParams(
        getTimeRangeQueryParams(timeRange, new Date(), customRange),
    );
    const query = params.toString();
    return api.get<PublicAnalyticsSummary>(
        query ? `/analytics/public-usage?${query}` : "/analytics/public-usage",
        { signal },
    );
};
