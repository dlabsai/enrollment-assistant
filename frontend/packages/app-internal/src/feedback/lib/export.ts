import type { ApiBlobResponse } from "@va/shared/lib/api-client";

interface FeedbackExportTimeSettings {
    browserTimeZone: string;
    browserLocale: string;
}

export const getFeedbackExportTimeSettings = (): FeedbackExportTimeSettings => {
    const resolvedOptions = new Intl.DateTimeFormat().resolvedOptions();
    return {
        browserTimeZone: resolvedOptions.timeZone,
        browserLocale: resolvedOptions.locale,
    };
};

const buildFeedbackExportFileName = (): string => {
    const date = new Date().toISOString().slice(0, 10);
    return `feedback-${date}.xlsx`;
};

export const downloadFeedbackExcel = ({
    blob,
    fileName,
}: ApiBlobResponse): void => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName ?? buildFeedbackExportFileName();
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => {
        URL.revokeObjectURL(url);
    }, 0);
};
