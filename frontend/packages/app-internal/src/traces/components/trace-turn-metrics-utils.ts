import { formatLocaleNumber } from "../../lib/number-format";
import { formatDurationMs } from "../lib/trace-utils";

export const getNumericAttribute = (
    attributes: Record<string, unknown>,
    key: string,
): number | undefined => {
    const value = attributes[key];
    if (typeof value === "number") {
        return value;
    }
    if (typeof value === "string") {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : undefined;
    }
    return undefined;
};

export const formatNumeric = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    if (Number.isInteger(value)) {
        return formatLocaleNumber(value);
    }
    return formatLocaleNumber(value, { maximumFractionDigits: 4 });
};

export const formatOffsetMs = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    if (value < 1000) {
        return `${formatLocaleNumber(Math.round(value))}ms`;
    }
    return `${formatLocaleNumber(value / 1000, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}s`;
};

export const formatOffset = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    if (value <= 0) {
        return "0ms";
    }
    return formatDurationMs(value);
};

export { formatTimestampWithSeconds } from "../../lib/date-format";
