import { Button } from "@va/shared/components/ui/button";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
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
import { useChatAnalyticsData } from "../hooks/use-chat-analytics-data";
import { ChatLengthChart } from "./chat-length-chart";
import { ChatSummaryCards } from "./chat-summary-cards";
import { ChatVolumeChart, MessagesVolumeChart } from "./chat-volume-chart";
import { MessagesByHourChart } from "./messages-by-hour-chart";
import { ResponseTimeChart } from "./response-time-chart";

const platformOptions = [
    { label: "All platforms", value: "both" },
    { label: "Internal", value: "internal" },
    { label: "Public", value: "public" },
] as const;

const analyticsFilterStorageKey = "internal-chat-analytics-filters";

type PlatformFilter = (typeof platformOptions)[number]["value"];

interface StoredAnalyticsFilters {
    platform?: PlatformFilter;
    timeRange?: TimeRangeValue;
    customRange?: {
        start?: string;
        end?: string;
    };
}

const isPlatformFilter = (value: string): value is PlatformFilter =>
    platformOptions.some((option) => option.value === value);

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
    range?: StoredAnalyticsFilters["customRange"],
): CustomTimeRange => ({
    start: parseStoredDate(range?.start),
    end: parseStoredDate(range?.end),
});

const parseStoredAnalyticsFilters = (
    value: string,
): StoredAnalyticsFilters | undefined => {
    try {
        const parsed: unknown = JSON.parse(value);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const customRangeValue = isRecord(parsed.customRange)
            ? parsed.customRange
            : undefined;
        const platformValue =
            typeof parsed.platform === "string" &&
            isPlatformFilter(parsed.platform)
                ? parsed.platform
                : undefined;
        const timeRangeValue =
            typeof parsed.timeRange === "string" &&
            isTimeRangeValue(parsed.timeRange)
                ? parsed.timeRange
                : undefined;
        return {
            platform: platformValue,
            timeRange: timeRangeValue,
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

const getStoredAnalyticsFilters = (): StoredAnalyticsFilters | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const stored = window.localStorage.getItem(analyticsFilterStorageKey);
    if (stored === null || stored === "") {
        return undefined;
    }
    return parseStoredAnalyticsFilters(stored);
};

export const AnalyticsPage = (): JSX.Element => {
    const storedFilters = useMemo(() => getStoredAnalyticsFilters(), []);
    const [platform, setPlatform] = useState<PlatformFilter>(() => {
        const storedPlatform = storedFilters?.platform;
        if (storedPlatform !== undefined) {
            return storedPlatform;
        }
        return "both";
    });
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
    const { summary, loading, hasLoaded, error, refresh } =
        useChatAnalyticsData(platform, timeRange, customRange);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        const payload: StoredAnalyticsFilters = {
            platform,
            timeRange,
            customRange: {
                start: customRange.start?.toISOString(),
                end: customRange.end?.toISOString(),
            },
        };
        window.localStorage.setItem(
            analyticsFilterStorageKey,
            JSON.stringify(payload),
        );
    }, [customRange, platform, timeRange]);

    if (loading && !hasLoaded) {
        return <LoadingState />;
    }

    if (error !== undefined || summary === undefined) {
        return (
            <PageError
                message={error ?? "Failed to load chat analytics."}
                onRetry={() => void refresh()}
            />
        );
    }

    return (
        <PageShell variant="dashboard">
            <PageHeader title="Chat Analytics">
                <PageHeaderGroup>
                    <ToggleGroup
                        aria-label="Platform"
                        onValueChange={(value) => {
                            const [nextValue] = value;
                            const next = isPlatformFilter(nextValue)
                                ? nextValue
                                : "both";
                            setPlatform(next);
                        }}
                        value={[platform]}
                        variant="outline"
                    >
                        {platformOptions.map((option) => (
                            <ToggleGroupItem
                                key={option.value}
                                value={option.value}
                            >
                                {option.label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </PageHeaderGroup>
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
                        setPlatform("both");
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
                <ChatSummaryCards summary={summary} />
            </PageSection>

            <PageSection className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
                <ChatVolumeChart
                    data={summary.daily}
                    timeRange={timeRange}
                />
                <MessagesVolumeChart
                    data={summary.daily}
                    timeRange={timeRange}
                />
                <ChatLengthChart
                    data={summary.length_buckets}
                    stats={summary.length_stats}
                />
                <ResponseTimeChart
                    data={summary.response_time_buckets}
                    stats={summary.response_time_stats}
                />
                <MessagesByHourChart data={summary.hourly_activity} />
            </PageSection>
        </PageShell>
    );
};
