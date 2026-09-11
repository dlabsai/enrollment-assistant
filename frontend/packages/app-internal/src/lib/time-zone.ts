import { CalendarDateTime } from "@internationalized/date";

export type AppFormatMode = "browser" | "eastern";

export interface AppFormatSettings {
    locale: string;
    mode: AppFormatMode;
    timeZone: string;
}

const EASTERN_FORMAT_SETTINGS = {
    locale: "en-US",
    timeZone: "America/New_York",
} as const;
const STORAGE_KEY = "internal-time-zone-mode";
const DEFAULT_MODE: AppFormatMode = "browser";

export const isAppFormatMode = (value: unknown): value is AppFormatMode =>
    value === "browser" || value === "eastern";

export const getAppFormatMode = (): AppFormatMode => {
    if (typeof window === "undefined") {
        return DEFAULT_MODE;
    }
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isAppFormatMode(stored) ? stored : DEFAULT_MODE;
};

export const getAppFormatSettings = (): AppFormatSettings => {
    const mode = getAppFormatMode();
    if (mode === "eastern") {
        return { mode, ...EASTERN_FORMAT_SETTINGS };
    }

    const browserSettings = new Intl.DateTimeFormat().resolvedOptions();
    return {
        locale: browserSettings.locale,
        mode,
        timeZone: browserSettings.timeZone || "UTC",
    };
};

export const setAppFormatMode = (mode: AppFormatMode): void => {
    window.localStorage.setItem(STORAGE_KEY, mode);
};

export const createDateInTimeZone = (
    timeZone: string,
    year: number,
    month: number,
    day: number,
    hour = 0,
    minute = 0,
    second = 0,
    millisecond = 0,
): Date =>
    new CalendarDateTime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        millisecond,
    ).toDate(timeZone);
