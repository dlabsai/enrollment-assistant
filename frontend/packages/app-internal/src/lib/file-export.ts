import type { ApiBlobResponse } from "@va/shared/lib/api-client";

export interface BrowserExportTimeSettings {
    browserTimeZone: string;
    browserLocale: string;
}

export const getBrowserExportTimeSettings = (): BrowserExportTimeSettings => {
    const resolvedOptions = new Intl.DateTimeFormat().resolvedOptions();
    return {
        browserTimeZone: resolvedOptions.timeZone,
        browserLocale: resolvedOptions.locale,
    };
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
