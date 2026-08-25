import type { ApiBlobResponse } from "@va/shared/lib/api-client";

import { downloadApiBlob } from "../../lib/file-export";

export { getBrowserExportTimeSettings as getFeedbackExportTimeSettings } from "../../lib/file-export";

const buildFeedbackExportFileName = (): string => {
    const date = new Date().toISOString().slice(0, 10);
    return `feedback-${date}.xlsx`;
};

export const downloadFeedbackExcel = (response: ApiBlobResponse): void => {
    downloadApiBlob(response, buildFeedbackExportFileName());
};
