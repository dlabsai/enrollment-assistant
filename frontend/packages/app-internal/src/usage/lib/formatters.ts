import { formatLocaleNumber } from "../../lib/number-format";

export const formatUsageDuration = (
    seconds: number | null | undefined,
): string => {
    if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
        return "-";
    }
    if (seconds < 1) {
        return `${formatLocaleNumber(Math.round(seconds * 1000))}ms`;
    }
    return `${formatLocaleNumber(seconds, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}s`;
};
