import { Button } from "@va/shared/components/ui/button";
import { Filter, RefreshCw } from "lucide-react";
import type { JSX } from "react";

import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { LoadingState, PageError } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import { usePersistedTimeRange } from "../../lib/hooks/use-persisted-time-range";
import { usePublicAnalyticsData } from "../hooks/use-public-analytics-data";
import { PublicDepthChart } from "./public-depth-chart";
import { PublicLeadsChart } from "./public-leads-chart";
import { PublicAnalyticsSummaryCards } from "./public-summary-cards";

const publicAnalyticsFilterStorageKey = "internal-public-analytics-filters";

export const PublicAnalyticsPage = (): JSX.Element => {
    const {
        timeRange,
        customRange,
        setTimeRange,
        setCustomRange,
        resetTimeRange,
    } = usePersistedTimeRange(publicAnalyticsFilterStorageKey, "30d");
    const { summary, loading, hasLoaded, error, refresh } =
        usePublicAnalyticsData(timeRange, customRange);

    if (loading && !hasLoaded) {
        return <LoadingState />;
    }

    if (error !== undefined || summary === undefined) {
        return (
            <PageError
                message={error ?? "Failed to load public analytics."}
                onRetry={refresh}
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
                    onClick={resetTimeRange}
                    variant="outline"
                >
                    <Filter data-icon="inline-start" />
                    Clear
                </Button>
                <Button
                    onClick={refresh}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection>
                <PublicAnalyticsSummaryCards summary={summary} />
            </PageSection>

            <PageSection className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
                <PublicLeadsChart
                    data={summary.series}
                    granularity={summary.time_granularity}
                />
                <PublicDepthChart data={summary.depth_buckets} />
            </PageSection>
        </PageShell>
    );
};
