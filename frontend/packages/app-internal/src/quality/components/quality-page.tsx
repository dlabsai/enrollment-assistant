import { useNavigate } from "@tanstack/react-router";
import { Button } from "@va/shared/components/ui/button";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import { Filter, RefreshCw } from "lucide-react";
import { type JSX, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../auth/contexts/auth-context";
import { hasPermission } from "../../auth/lib/permissions";
import { useDashboardUserFilter } from "../../chats/hooks/use-dashboard-user-filter";
import { parseStoredUserFilter } from "../../chats/lib/user-filter-options";
import type { ChatUserOption } from "../../chats/types";
import { HelpButton } from "../../components/help-dialog";
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
import { useQualityData } from "../hooks/use-quality-data";
import {
    getQualityDrilldownRange,
    getResponsivenessDurationSearch,
} from "../lib/drilldown";
import type {
    QualityFeedbackRating,
    QualityGuardrailStatus,
    QualityPlatform,
    QualityResponseTimeBucket,
    QualityResponsivenessPoint,
    QualitySeriesPoint,
} from "../types";
import {
    FeedbackChart,
    GuardrailChart,
    ResponseTimeDistributionChart,
    ResponsivenessChart,
} from "./quality-charts";
import { QualityHelp } from "./quality-help";
import {
    FeedbackSummaryCards,
    GuardrailSummaryCards,
    ResponsivenessSummaryCards,
} from "./quality-summary-cards";

const platformOptions = [
    { label: "All platforms", value: "both" },
    { label: "Internal", value: "internal" },
    { label: "Public", value: "public" },
] as const;

const qualityFilterStorageKey = "internal-quality-filters";
const defaultStaffFilter: ChatUserOption = {
    name: "Staff",
    email: "__owner_group:staff",
    platform: "internal",
    ownerGroup: "staff",
};

interface StoredQualityFilters {
    platform?: QualityPlatform;
    timeRange?: TimeRangeValue;
    customRange?: {
        start?: string;
        end?: string;
    };
    selectedUser?: ChatUserOption;
}

const isPlatform = (value: string): value is QualityPlatform =>
    platformOptions.some((option) => option.value === value);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

const parseDate = (value?: string): Date | undefined => {
    if (value === undefined || value === "") {
        return undefined;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

const loadStoredFilters = (): StoredQualityFilters | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const raw = window.localStorage.getItem(qualityFilterStorageKey);
    if (raw === null || raw === "") {
        return undefined;
    }
    try {
        const parsed: unknown = JSON.parse(raw);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const custom = isRecord(parsed.customRange)
            ? parsed.customRange
            : undefined;
        return {
            platform:
                typeof parsed.platform === "string" &&
                isPlatform(parsed.platform)
                    ? parsed.platform
                    : undefined,
            timeRange:
                typeof parsed.timeRange === "string" &&
                isTimeRangeValue(parsed.timeRange)
                    ? parsed.timeRange
                    : undefined,
            customRange: {
                start:
                    typeof custom?.start === "string"
                        ? custom.start
                        : undefined,
                end: typeof custom?.end === "string" ? custom.end : undefined,
            },
            selectedUser: parseStoredUserFilter(parsed.selectedUser),
        };
    } catch {
        return undefined;
    }
};

export const QualityPage = (): JSX.Element => {
    const navigate = useNavigate();
    const { user } = useAuth();
    const storedFilters = useMemo(() => loadStoredFilters(), []);
    const [platform, setPlatform] = useState<QualityPlatform>(
        storedFilters?.platform ?? "internal",
    );
    const userFilter = useDashboardUserFilter({
        initialSelectedUser:
            storedFilters === undefined
                ? defaultStaffFilter
                : storedFilters.selectedUser,
        platform,
    });
    const [timeRange, setTimeRange] = useState<TimeRangeValue>(
        storedFilters?.timeRange ?? "30d",
    );
    const [customRange, setCustomRange] = useState<CustomTimeRange>(() => ({
        start: parseDate(storedFilters?.customRange?.start),
        end: parseDate(storedFilters?.customRange?.end),
    }));
    const [helpOpen, setHelpOpen] = useState(false);
    const { appliedRange, summary, loading, hasLoaded, error, refresh } =
        useQualityData(
            platform,
            timeRange,
            customRange,
            userFilter.userFilterParams.userEmail,
            userFilter.userFilterParams.userGroup,
        );
    const canInspectSelectedPlatform =
        platform === "internal" ||
        user?.group.slug === "admin" ||
        user?.group.slug === "dev";
    const canInspectMessages =
        !loading &&
        hasPermission(user, "access_messages") &&
        canInspectSelectedPlatform;
    const canInspectFeedback =
        !loading &&
        hasPermission(user, "access_chats") &&
        canInspectSelectedPlatform;

    useEffect(() => {
        const payload: StoredQualityFilters = {
            platform,
            timeRange,
            customRange: {
                start: customRange.start?.toISOString(),
                end: customRange.end?.toISOString(),
            },
            selectedUser: userFilter.selectedUser,
        };
        window.localStorage.setItem(
            qualityFilterStorageKey,
            JSON.stringify(payload),
        );
    }, [customRange, platform, timeRange, userFilter.selectedUser]);

    if (loading && !hasLoaded) {
        return <LoadingState />;
    }
    if (
        error !== undefined ||
        summary === undefined ||
        appliedRange === undefined
    ) {
        return (
            <PageError
                message={error ?? "Failed to load quality data."}
                onRetry={refresh}
            />
        );
    }

    const currentBounds = appliedRange;
    const ownerSearch = {
        userEmail: userFilter.userFilterParams.userEmail,
        userGroup: userFilter.userFilterParams.userGroup,
    };
    const platformSearch = platform === "both" ? undefined : platform;

    const inspectMessages = (
        status?: QualityGuardrailStatus,
        point?: QualitySeriesPoint,
    ): void => {
        if (!canInspectMessages) {
            return;
        }
        const range = getQualityDrilldownRange(currentBounds, point);
        void navigate({
            to: "/messages",
            search: {
                excludeDraft: true,
                guardrailStatus: status ?? "all",
                platform: platformSearch,
                role: "assistant",
                ...ownerSearch,
                ...range,
            },
        });
    };

    const inspectResponsiveness = (
        point?: QualityResponsivenessPoint,
        bucket?: QualityResponseTimeBucket,
    ): void => {
        if (!canInspectMessages) {
            return;
        }
        const range = getQualityDrilldownRange(currentBounds, point);
        void navigate({
            to: "/messages",
            search: {
                descending: true,
                excludeDraft: true,
                guardrailStatus: "all",
                ...getResponsivenessDurationSearch(bucket),
                platform: platformSearch,
                role: "assistant",
                sortBy: "generation_time_ms",
                ...ownerSearch,
                ...range,
            },
        });
    };

    const inspectFeedback = (
        rating?: QualityFeedbackRating,
        point?: QualitySeriesPoint,
    ): void => {
        if (!canInspectFeedback) {
            return;
        }
        const range = getQualityDrilldownRange(currentBounds, point);
        void navigate({
            to: "/feedback",
            search: {
                chat: undefined,
                excludeDraft: true,
                message: undefined,
                platform: platformSearch,
                rating,
                ...ownerSearch,
                ...range,
            },
        });
    };

    return (
        <PageShell variant="dashboard">
            <PageHeader
                title="Quality"
                titleAddon={
                    <HelpButton
                        iconOnly
                        label="About quality metrics"
                        onClick={() => {
                            setHelpOpen(true);
                        }}
                    />
                }
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
                    <ToggleGroup
                        aria-label="Platform"
                        onValueChange={(value) => {
                            const [nextValue] = value;
                            const nextPlatform = isPlatform(nextValue)
                                ? nextValue
                                : "both";
                            if (nextPlatform !== platform) {
                                userFilter.clear();
                                setPlatform(nextPlatform);
                            }
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
                        userFilter.handleChange(defaultStaffFilter);
                        setPlatform("internal");
                        setTimeRange("30d");
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
                <ResponsivenessSummaryCards
                    canInspect={canInspectMessages}
                    onInspect={() => {
                        inspectResponsiveness();
                    }}
                    summary={summary.summary}
                />
            </PageSection>

            <PageSection>
                <ResponsivenessChart
                    canInspect={canInspectMessages}
                    data={summary.responsiveness_series}
                    granularity={summary.time_granularity}
                    onInspect={(point) => {
                        inspectResponsiveness(point);
                    }}
                />
            </PageSection>

            <PageSection>
                <ResponseTimeDistributionChart
                    canInspect={canInspectMessages}
                    data={summary.response_time_buckets}
                    onInspect={(bucket) => {
                        inspectResponsiveness(undefined, bucket);
                    }}
                />
            </PageSection>

            <PageSection>
                <FeedbackSummaryCards
                    canInspect={canInspectFeedback}
                    onInspect={(rating) => {
                        inspectFeedback(rating);
                    }}
                    summary={summary.summary}
                />
            </PageSection>

            <PageSection>
                <FeedbackChart
                    canInspect={canInspectFeedback}
                    data={summary.series}
                    granularity={summary.time_granularity}
                    onInspect={(point, rating) => {
                        inspectFeedback(rating, point);
                    }}
                />
            </PageSection>

            <PageSection>
                <GuardrailSummaryCards
                    canInspect={canInspectMessages}
                    onInspect={(status) => {
                        inspectMessages(status);
                    }}
                    summary={summary.summary}
                />
            </PageSection>

            <PageSection>
                <GuardrailChart
                    canInspect={canInspectMessages}
                    data={summary.series}
                    granularity={summary.time_granularity}
                    onInspect={(point, status) => {
                        inspectMessages(status, point);
                    }}
                />
            </PageSection>

            <QualityHelp
                onOpenChange={setHelpOpen}
                open={helpOpen}
            />
        </PageShell>
    );
};
