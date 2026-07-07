import { Button } from "@va/shared/components/ui/button";
import { Filter, RefreshCw } from "lucide-react";
import { type JSX, useEffect, useMemo, useState } from "react";

import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { LoadingState, PageError } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import {
    type CustomTimeRange,
    isTimeRangeValue,
    type TimeRangeValue,
} from "../../lib/time-range";
import { usePublicUsageData } from "../../usage/hooks/use-public-usage-data";
import { PublicLeadsChart } from "./public-leads-chart";
import { PublicUsageSummaryCards } from "./public-usage-summary";

const publicAnalyticsFilterStorageKey = "internal-public-analytics-filters";

interface StoredPublicAnalyticsFilters {
    timeRange?: TimeRangeValue;
    customRange?: {
        start?: string;
        end?: string;
    };
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

const parseStoredDate = (value?: string): Date | undefined => {
    if (value === undefined || value === "") {
        return undefined;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

const parseStoredCustomRange = (
    range?: StoredPublicAnalyticsFilters["customRange"],
): CustomTimeRange => ({
    start: parseStoredDate(range?.start),
    end: parseStoredDate(range?.end),
});

const parseStoredPublicAnalyticsFilters = (
    value: string,
): StoredPublicAnalyticsFilters | undefined => {
    try {
        const parsed: unknown = JSON.parse(value);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const customRangeValue = isRecord(parsed.customRange)
            ? parsed.customRange
            : undefined;
        return {
            timeRange:
                typeof parsed.timeRange === "string" &&
                isTimeRangeValue(parsed.timeRange)
                    ? parsed.timeRange
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
        };
    } catch {
        return undefined;
    }
};

const getStoredPublicAnalyticsFilters = ():
    | StoredPublicAnalyticsFilters
    | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const stored = window.localStorage.getItem(publicAnalyticsFilterStorageKey);
    if (stored === null || stored === "") {
        return undefined;
    }
    return parseStoredPublicAnalyticsFilters(stored);
};

export const PublicAnalyticsPage = (): JSX.Element => {
    const storedFilters = useMemo(() => getStoredPublicAnalyticsFilters(), []);
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
    const { summary, loading, hasLoaded, error, refresh } = usePublicUsageData(
        timeRange,
        customRange,
    );

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        const payload: StoredPublicAnalyticsFilters = {
            timeRange,
            customRange: {
                start: customRange.start?.toISOString(),
                end: customRange.end?.toISOString(),
            },
        };
        window.localStorage.setItem(
            publicAnalyticsFilterStorageKey,
            JSON.stringify(payload),
        );
    }, [customRange, timeRange]);

    if (loading && !hasLoaded) {
        return <LoadingState />;
    }

    if (error !== undefined || summary === undefined) {
        return (
            <PageError
                message={error ?? "Failed to load public analytics."}
                onRetry={() => void refresh()}
            />
        );
    }

    return (
        <PageShell variant="dashboard">
            <PageHeader title="Public Analytics">
                <PageHeaderGroup>
                    <TimeRangeFilter
                        customRange={customRange}
                        onChange={setTimeRange}
                        onCustomRangeChange={setCustomRange}
                        value={timeRange}
                    />
                </PageHeaderGroup>
                <Button
                    onClick={() => {
                        setTimeRange("30d");
                        setCustomRange({});
                    }}
                    variant="outline"
                >
                    <Filter data-icon="inline-start" />
                    Clear
                </Button>
                <Button
                    onClick={() => void refresh()}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection>
                <PublicUsageSummaryCards summary={summary} />
            </PageSection>

            <PageSection className="grid grid-cols-1 gap-4">
                <PublicLeadsChart
                    data={summary.daily}
                    timeRange={timeRange}
                />
            </PageSection>
        </PageShell>
    );
};
