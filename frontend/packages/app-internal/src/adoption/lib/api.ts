import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { AdoptionSummary } from "../types";

export const fetchAdoptionSummary = async (
    api: AuthenticatedApi,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    userEmail?: string,
    userGroup?: "staff" | "devs",
    signal?: AbortSignal,
): Promise<AdoptionSummary> => {
    const params = new URLSearchParams(
        getTimeRangeQueryParams(timeRange, new Date(), customRange),
    );
    params.set(
        "browser_time_zone",
        new Intl.DateTimeFormat().resolvedOptions().timeZone,
    );
    if (userEmail !== undefined && userEmail !== "") {
        params.set("user_email", userEmail);
    }
    if (userGroup !== undefined) {
        params.set("user_group", userGroup);
    }
    return api.get<AdoptionSummary>(
        `/analytics/adoption?${params.toString()}`,
        { signal },
    );
};
