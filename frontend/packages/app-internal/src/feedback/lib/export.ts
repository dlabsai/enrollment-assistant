import type { ApiBlobResponse } from "@va/shared/lib/api-client";

import { downloadApiBlob, formatExportDate } from "../../lib/file-export";

const buildFeedbackExportFileName = (): string =>
    `feedback-${formatExportDate()}.xlsx`;

export const downloadFeedbackExcel = (response: ApiBlobResponse): void => {
    downloadApiBlob(response, buildFeedbackExportFileName());
};
