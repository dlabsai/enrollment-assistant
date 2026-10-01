import { useCallback, useEffect, useState } from "react";

import {
    type CustomTimeRange,
    isTimeRangeValue,
    type TimeRangeValue,
} from "../time-range";

interface PersistedTimeRangeState {
    timeRange: TimeRangeValue;
    customRange: CustomTimeRange;
}

interface UsePersistedTimeRangeResult extends PersistedTimeRangeState {
    setTimeRange: (value: TimeRangeValue) => void;
    setCustomRange: (value: CustomTimeRange) => void;
    resetTimeRange: () => void;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

const parseStoredDate = (value: unknown): Date | undefined => {
    if (typeof value !== "string" || value === "") {
        return undefined;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

const loadTimeRange = (
    storageKey: string,
    defaultTimeRange: TimeRangeValue,
): PersistedTimeRangeState => {
    if (typeof window === "undefined") {
        return { timeRange: defaultTimeRange, customRange: {} };
    }
    const stored = window.localStorage.getItem(storageKey);
    if (stored === null || stored === "") {
        return { timeRange: defaultTimeRange, customRange: {} };
    }
    try {
        const parsed: unknown = JSON.parse(stored);
        if (!isRecord(parsed)) {
            return { timeRange: defaultTimeRange, customRange: {} };
        }
        const customRange = isRecord(parsed.customRange)
            ? parsed.customRange
            : undefined;
        return {
            timeRange:
                typeof parsed.timeRange === "string" &&
                isTimeRangeValue(parsed.timeRange)
                    ? parsed.timeRange
                    : defaultTimeRange,
            customRange: {
                start: parseStoredDate(customRange?.start),
                end: parseStoredDate(customRange?.end),
            },
        };
    } catch {
        return { timeRange: defaultTimeRange, customRange: {} };
    }
};

export const usePersistedTimeRange = (
    storageKey: string,
    defaultTimeRange: TimeRangeValue,
): UsePersistedTimeRangeResult => {
    const [state, setState] = useState<PersistedTimeRangeState>(() =>
        loadTimeRange(storageKey, defaultTimeRange),
    );

    useEffect(() => {
        window.localStorage.setItem(
            storageKey,
            JSON.stringify({
                timeRange: state.timeRange,
                customRange: {
                    start: state.customRange.start?.toISOString(),
                    end: state.customRange.end?.toISOString(),
                },
            }),
        );
    }, [state, storageKey]);

    const setTimeRange = useCallback((timeRange: TimeRangeValue): void => {
        setState((current) => ({ ...current, timeRange }));
    }, []);
    const setCustomRange = useCallback((customRange: CustomTimeRange): void => {
        setState((current) => ({ ...current, customRange }));
    }, []);
    const resetTimeRange = useCallback((): void => {
        setState({ timeRange: defaultTimeRange, customRange: {} });
    }, [defaultTimeRange]);

    return {
        ...state,
        setTimeRange,
        setCustomRange,
        resetTimeRange,
    };
};
