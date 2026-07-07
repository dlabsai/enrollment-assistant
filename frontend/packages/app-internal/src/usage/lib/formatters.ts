import { formatLocaleNumber } from "../../lib/number-format";

export const formatUsageCost = (cost: number | null | undefined): string => {
    if (cost === null || cost === undefined || !Number.isFinite(cost)) {
        return "-";
    }
    if (cost > 0 && cost < 0.0001) {
        return `<$${formatLocaleNumber(0.0001, {
            minimumFractionDigits: 4,
            maximumFractionDigits: 4,
        })}`;
    }

    const fractionDigits = cost > 0 && cost < 0.01 ? 4 : 2;
    return `$${formatLocaleNumber(cost, {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
    })}`;
};

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
