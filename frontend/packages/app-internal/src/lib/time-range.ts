export type TimeRangeValue =
    | "24h"
    | "7d"
    | "14d"
    | "30d"
    | "60d"
    | "90d"
    | "180d"
    | "365d"
    | "all"
    | "custom";

export interface CustomTimeRange {
    start?: Date;
    end?: Date;
}

interface TimeRangeOption {
    label: string;
    value: TimeRangeValue;
    durationMs?: number;
}

const DAY_MS = 24 * 60 * 60 * 1000;

export const timeRangeOptions: TimeRangeOption[] = [
    { label: "Last 24 hours", value: "24h", durationMs: DAY_MS },
    { label: "Last 7 days", value: "7d", durationMs: 7 * DAY_MS },
    { label: "Last 14 days", value: "14d", durationMs: 14 * DAY_MS },
    { label: "Last 30 days", value: "30d", durationMs: 30 * DAY_MS },
    { label: "Last 60 days", value: "60d", durationMs: 60 * DAY_MS },
    { label: "Last 90 days", value: "90d", durationMs: 90 * DAY_MS },
    { label: "Last 180 days", value: "180d", durationMs: 180 * DAY_MS },
    { label: "Last 365 days", value: "365d", durationMs: 365 * DAY_MS },
    { label: "All time", value: "all" },
    { label: "Custom range", value: "custom" },
];

export const isTimeRangeValue = (value: string): value is TimeRangeValue =>
    timeRangeOptions.some((option) => option.value === value);

const getTimeRangeStart = (
    range: TimeRangeValue,
    referenceDate: Date = new Date(),
): Date | undefined => {
    if (range === "custom") {
        return undefined;
    }
    const option = timeRangeOptions.find((item) => item.value === range);
    if (option?.durationMs === undefined) {
        return undefined;
    }
    return new Date(referenceDate.getTime() - option.durationMs);
};

const getCustomRangeQueryParams = (
    customRange?: CustomTimeRange,
): { start?: string; end?: string } => {
    if (!customRange?.start) {
        return {};
    }

    const start = customRange.start.toISOString();
    if (!customRange.end) {
        return { start };
    }
    return { start, end: customRange.end.toISOString() };
};

export const getTimeRangeQueryParams = (
    range: TimeRangeValue,
    referenceDate: Date = new Date(),
    customRange?: CustomTimeRange,
): { start?: string; end?: string } => {
    if (range === "custom") {
        return getCustomRangeQueryParams(customRange);
    }

    const startDate = getTimeRangeStart(range, referenceDate);
    if (!startDate) {
        return {};
    }
    return {
        start: startDate.toISOString(),
        end: referenceDate.toISOString(),
    };
};
