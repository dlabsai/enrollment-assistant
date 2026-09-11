import type { ApiBlobResponse } from "@va/shared/lib/api-client";

import { getAppFormatSettings } from "./time-zone";

export interface ExportFormatSettings {
    locale: string;
    timeZone: string;
}

export const getExportFormatSettings = (): ExportFormatSettings => {
    const { locale, timeZone } = getAppFormatSettings();
    return { locale, timeZone };
};

export const formatExportDate = (value: Date = new Date()): string => {
    const { timeZone } = getAppFormatSettings();
    const parts = new Map(
        new Intl.DateTimeFormat("en-US", {
            day: "2-digit",
            month: "2-digit",
            timeZone,
            year: "numeric",
        })
            .formatToParts(value)
            .map((part) => [part.type, part.value]),
    );
    return `${parts.get("year")}-${parts.get("month")}-${parts.get("day")}`;
};

export const downloadApiBlob = (
    { blob, fileName }: ApiBlobResponse,
    fallbackFileName: string,
): void => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName ?? fallbackFileName;
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
};
