import {
    getDefaultDataTablePageSize,
    isDataTablePageSize,
} from "../../components/data-table-constants";
import { getAppFormatSettings } from "../../lib/time-zone";
import type { ReviewState, ScreeningSummary } from "../types";

type Period = Pick<ScreeningSummary, "start" | "end">;

const formatPeriod = (period: Period, withTime: boolean): string => {
    const settings = getAppFormatSettings();
    const options: Intl.DateTimeFormatOptions = {
        dateStyle: "medium",
        timeZone: settings.timeZone,
    };
    if (withTime) {
        options.timeStyle = "short";
    }
    return new Intl.DateTimeFormat(settings.locale, options).formatRange(
        new Date(period.start),
        new Date(period.end),
    );
};

export const formatScreeningPeriod = (period: Period): string =>
    formatPeriod(period, true);
export const formatScreeningDateRange = (period: Period): string =>
    formatPeriod(period, false);

export const decisionLabel = (state: ReviewState): string =>
    ({
        needs_review: "Needs review",
        confirmed: "Confirmed",
        dismissed: "Dismissed",
    })[state];

export const screeningLabel = (screening: ScreeningSummary): string => {
    if (screening.admission_error !== null) {
        return "Incomplete";
    }
    if (screening.messages === 0) {
        return "No messages";
    }
    if (screening.pending > 0) {
        return "Processing";
    }
    if (screening.errors > 0 || screening.deleted > 0) {
        return "Incomplete";
    }
    return "Complete";
};

export type ComplianceStatusVariant =
    | "default"
    | "destructive"
    | "outline"
    | "secondary";

export const screeningStatusVariant = (
    screening: ScreeningSummary,
): ComplianceStatusVariant => {
    if (
        screening.admission_error !== null ||
        screening.messages === 0 ||
        screening.errors > 0 ||
        screening.deleted > 0
    ) {
        return "destructive";
    }
    return screening.pending > 0 ? "secondary" : "outline";
};

export interface ComplianceSearch {
    page?: number;
    pageSize?: number;
}

export const serializeComplianceSearch = (
    pageIndex: number,
    pageSize: number,
): ComplianceSearch => ({
    ...(pageIndex === 0 ? {} : { page: pageIndex + 1 }),
    ...(pageSize === getDefaultDataTablePageSize() ? {} : { pageSize }),
});

export const validateComplianceSearch = (
    search: Record<string, unknown>,
): ComplianceSearch => {
    const page =
        typeof search.page === "number" &&
        Number.isSafeInteger(search.page) &&
        search.page > 0
            ? search.page
            : 1;
    const pageSize =
        typeof search.pageSize === "number" &&
        isDataTablePageSize(search.pageSize)
            ? search.pageSize
            : getDefaultDataTablePageSize();
    return serializeComplianceSearch(page - 1, pageSize);
};
