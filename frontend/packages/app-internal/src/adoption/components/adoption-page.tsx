import { Button } from "@va/shared/components/ui/button";
import { Filter, RefreshCw } from "lucide-react";
import { type JSX, useEffect, useMemo, useState } from "react";

import { useDashboardUserFilter } from "../../chats/hooks/use-dashboard-user-filter";
import { parseStoredUserFilter } from "../../chats/lib/user-filter-options";
import type { ChatUserOption } from "../../chats/types";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { LoadingState, PageError } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import { UserFilterPopover } from "../../components/user-filter-popover";
import {
    type CustomTimeRange,
    isTimeRangeValue,
    type TimeRangeValue,
} from "../../lib/time-range";
import { useAdoptionData } from "../hooks/use-adoption-data";
import { AdoptionChart } from "./adoption-chart";
import { AdoptionHelp } from "./adoption-help";
import { AdoptionSummaryCards } from "./adoption-summary-cards";

const adoptionFilterStorageKey = "internal-adoption-filters";

interface StoredAdoptionFilters {
    timeRange?: TimeRangeValue;
    customRange?: {
        start?: string;
        end?: string;
    };
    selectedUser?: ChatUserOption;
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

const parseStoredAdoptionFilters = (
    value: string,
): StoredAdoptionFilters | undefined => {
    try {
        const parsed: unknown = JSON.parse(value);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const customRange = isRecord(parsed.customRange)
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
                    typeof customRange?.start === "string"
                        ? customRange.start
                        : undefined,
                end:
                    typeof customRange?.end === "string"
                        ? customRange.end
                        : undefined,
            },
            selectedUser: parseStoredUserFilter(parsed.selectedUser),
        };
    } catch {
        return undefined;
    }
};

const getStoredAdoptionFilters = (): StoredAdoptionFilters | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const stored = window.localStorage.getItem(adoptionFilterStorageKey);
    return stored === null || stored === ""
        ? undefined
        : parseStoredAdoptionFilters(stored);
};

export const AdoptionPage = (): JSX.Element => {
    const storedFilters = useMemo(() => getStoredAdoptionFilters(), []);
    const [timeRange, setTimeRange] = useState<TimeRangeValue>(
        () => storedFilters?.timeRange ?? "90d",
    );
    const [customRange, setCustomRange] = useState<CustomTimeRange>(() => ({
        start: parseStoredDate(storedFilters?.customRange?.start),
        end: parseStoredDate(storedFilters?.customRange?.end),
    }));
    const userFilter = useDashboardUserFilter({
        initialSelectedUser: storedFilters?.selectedUser,
        platform: "internal",
    });
    const { summary, loading, hasLoaded, error, refresh } = useAdoptionData(
        timeRange,
        customRange,
        userFilter.userFilterParams.userEmail,
        userFilter.userFilterParams.userGroup,
    );

    useEffect(() => {
        const payload: StoredAdoptionFilters = {
            timeRange,
            customRange: {
                start: customRange.start?.toISOString(),
                end: customRange.end?.toISOString(),
            },
            selectedUser: userFilter.selectedUser,
        };
        window.localStorage.setItem(
            adoptionFilterStorageKey,
            JSON.stringify(payload),
        );
    }, [customRange, timeRange, userFilter.selectedUser]);

    if (loading && !hasLoaded) {
        return <LoadingState />;
    }

    if (error !== undefined || summary === undefined) {
        return (
            <PageError
                message={error ?? "Failed to load adoption data."}
                onRetry={refresh}
            />
        );
    }

    return (
        <PageShell variant="dashboard">
            <PageHeader
                title="Adoption"
                titleAddon={<AdoptionHelp />}
            >
                <UserFilterPopover
                    label={userFilter.label}
                    loading={userFilter.loading}
                    onChange={userFilter.handleChange}
                    onOpenChange={userFilter.handleOpenChange}
                    onSearchInputChange={userFilter.handleSearchInputChange}
                    open={userFilter.open}
                    options={userFilter.options}
                    searchInput={userFilter.searchInput}
                />
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
                        userFilter.clear();
                        setTimeRange("90d");
                        setCustomRange({});
                    }}
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
                <AdoptionSummaryCards summary={summary} />
            </PageSection>

            <PageSection className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
                <AdoptionChart
                    data={summary.daily}
                    description="Distinct users who sent a message each day"
                    metric="daily_active_users"
                    title="Daily active users"
                />
                <AdoptionChart
                    data={summary.daily}
                    description="Distinct users active in each rolling 30-day window"
                    metric="monthly_active_users"
                    title="Monthly active users"
                />
            </PageSection>
        </PageShell>
    );
};
