import { getAppFormatSettings } from "./time-zone";

export type TimeGranularity = "hour" | "day" | "week" | "month";

export const getTimeSeriesBucketRange = (point: {
    bucket_start: string;
    bucket_end: string;
}): { start: string; endBefore: string; timeRange: "custom" } => ({
    start: point.bucket_start,
    endBefore: point.bucket_end,
    timeRange: "custom",
});

export const timeGranularityLabel: Record<TimeGranularity, string> = {
    hour: "Hourly",
    day: "Daily",
    week: "Weekly",
    month: "Monthly",
};

const { locale: appLocale, timeZone: appTimeZone } = getAppFormatSettings();
const formatters: Record<
    TimeGranularity,
    { tick: Intl.DateTimeFormat; tooltip: Intl.DateTimeFormat }
> = {
    hour: {
        tick: new Intl.DateTimeFormat(appLocale, {
            month: "short",
            day: "numeric",
            hour: "numeric",
            timeZone: appTimeZone,
        }),
        tooltip: new Intl.DateTimeFormat(appLocale, {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "numeric",
            timeZone: appTimeZone,
        }),
    },
    day: {
        tick: new Intl.DateTimeFormat(appLocale, {
            month: "short",
            day: "numeric",
            timeZone: appTimeZone,
        }),
        tooltip: new Intl.DateTimeFormat(appLocale, {
            year: "numeric",
            month: "short",
            day: "numeric",
            timeZone: appTimeZone,
        }),
    },
    week: {
        tick: new Intl.DateTimeFormat(appLocale, {
            month: "short",
            day: "numeric",
            timeZone: appTimeZone,
        }),
        tooltip: new Intl.DateTimeFormat(appLocale, {
            year: "numeric",
            month: "short",
            day: "numeric",
            timeZone: appTimeZone,
        }),
    },
    month: {
        tick: new Intl.DateTimeFormat(appLocale, {
            month: "short",
            year: "2-digit",
            timeZone: appTimeZone,
        }),
        tooltip: new Intl.DateTimeFormat(appLocale, {
            year: "numeric",
            month: "long",
            timeZone: appTimeZone,
        }),
    },
};

export const formatTimeSeriesTick = (
    value: string,
    granularity: TimeGranularity,
): string => formatters[granularity].tick.format(new Date(value));

export const formatTimeSeriesTooltipLabel = (
    value: unknown,
    granularity: TimeGranularity,
): string =>
    typeof value === "string" || typeof value === "number"
        ? formatters[granularity].tooltip.format(new Date(value))
        : "";
