import type { TimeRangeValue } from "./time-range";

const hourlyTickFormatter = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
});

const dailyTickFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
});

const hourlyTooltipFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
});

export const isHourlyTimeRange = (timeRange: TimeRangeValue): boolean =>
    timeRange === "24h";

export const formatTimeSeriesTick = (
    value: string,
    timeRange: TimeRangeValue,
): string => {
    const date = new Date(value);
    return isHourlyTimeRange(timeRange)
        ? hourlyTickFormatter.format(date)
        : dailyTickFormatter.format(date);
};

export const formatTimeSeriesTooltipLabel = (
    value: string,
    timeRange: TimeRangeValue,
): string => {
    const date = new Date(value);
    return isHourlyTimeRange(timeRange)
        ? hourlyTooltipFormatter.format(date)
        : dailyTickFormatter.format(date);
};
