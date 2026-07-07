import { Streamdown } from "@va/shared/components/streamdown";
import type { JSX } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import { isRecord } from "../lib/trace-utils";

export const stringifyValue = (value: unknown): string => {
    if (value === undefined) {
        return "-";
    }
    if (value === null) {
        return "null";
    }
    if (typeof value === "string") {
        return value;
    }
    if (typeof value === "number") {
        return Number.isFinite(value)
            ? formatLocaleNumber(value, { maximumFractionDigits: 4 })
            : String(value);
    }
    if (typeof value === "boolean") {
        return String(value);
    }
    return JSON.stringify(value, undefined, 2);
};

const isIdentifierKey = (key: string): boolean => {
    const normalizedKey = key.toLowerCase();
    return (
        normalizedKey === "id" ||
        normalizedKey === "ids" ||
        normalizedKey.endsWith("_id") ||
        normalizedKey.endsWith("_ids")
    );
};

export const stringifyFieldValue = (key: string, value: unknown): string => {
    if (
        typeof value === "number" &&
        Number.isFinite(value) &&
        isIdentifierKey(key)
    ) {
        return String(value);
    }
    return stringifyValue(value);
};

export const renderStructuredValue = (value: unknown): JSX.Element => {
    if (isRecord(value)) {
        return (
            <div className="space-y-1 text-xs">
                {Object.entries(value).map(([key, entry]) => (
                    <div
                        className="grid grid-cols-[140px_1fr] items-start gap-x-2"
                        key={key}
                    >
                        <div className="font-semibold break-all uppercase">
                            {key}
                        </div>
                        <div className="text-muted-foreground whitespace-pre-wrap">
                            {stringifyFieldValue(key, entry)}
                        </div>
                    </div>
                ))}
            </div>
        );
    }
    if (Array.isArray(value)) {
        return (
            <div className="text-muted-foreground text-xs whitespace-pre-wrap">
                {stringifyValue(value)}
            </div>
        );
    }
    return (
        <div className="text-muted-foreground text-xs whitespace-pre-wrap">
            {stringifyValue(value)}
        </div>
    );
};

export const renderMarkdownValue = (value: unknown): JSX.Element => {
    const text = typeof value === "string" ? value : stringifyValue(value);
    return <Streamdown className="max-w-none break-words">{text}</Streamdown>;
};

export const renderPlainTextValue = (value: unknown): JSX.Element => (
    <div className="text-sm break-words whitespace-pre-wrap">
        {stringifyValue(value)}
    </div>
);
