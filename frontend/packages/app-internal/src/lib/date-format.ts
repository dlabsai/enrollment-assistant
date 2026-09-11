import { getAppFormatSettings } from "./time-zone";

const { locale: appLocale, timeZone: appTimeZone } = getAppFormatSettings();
const currentYearMessageTimestampFormatter = new Intl.DateTimeFormat(
    appLocale,
    {
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
        timeZone: appTimeZone,
    },
);

const olderMessageTimestampFormatter = new Intl.DateTimeFormat(appLocale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: appTimeZone,
});

const tableTimestampFormatter = new Intl.DateTimeFormat(appLocale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: appTimeZone,
});

const yearFormatter = new Intl.DateTimeFormat(appLocale, {
    timeZone: appTimeZone,
    year: "numeric",
});

const toDate = (value: number | string | Date): Date =>
    value instanceof Date ? value : new Date(value);

const isValidDate = (date: Date): boolean => Number.isFinite(date.getTime());

export const formatMessageTimestamp = (
    value: number | string | Date | null | undefined,
    now: Date = new Date(),
): string => {
    if (value === null || value === undefined || value === "") {
        return "-";
    }
    const date = toDate(value);
    if (!isValidDate(date)) {
        return "-";
    }
    return yearFormatter.format(date) === yearFormatter.format(now)
        ? currentYearMessageTimestampFormatter.format(date)
        : olderMessageTimestampFormatter.format(date);
};

export const formatTableTimestamp = (
    value: number | string | Date | null | undefined,
): string => {
    if (value === null || value === undefined || value === "") {
        return "-";
    }
    const date = toDate(value);
    return isValidDate(date) ? tableTimestampFormatter.format(date) : "-";
};
