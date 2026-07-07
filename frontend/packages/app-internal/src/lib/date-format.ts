const currentYearMessageTimestampFormatter = new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
});

const olderMessageTimestampFormatter = new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
});

const tableTimestampFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
});

const timestampWithSecondsFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
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
    return date.getFullYear() === now.getFullYear()
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

export const formatTimestampWithSeconds = (
    value: number | string | Date | null | undefined,
): string => {
    if (value === null || value === undefined || value === "") {
        return "-";
    }
    const date = toDate(value);
    return isValidDate(date) ? timestampWithSecondsFormatter.format(date) : "-";
};
