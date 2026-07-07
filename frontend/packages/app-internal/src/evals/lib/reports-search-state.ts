import {
    DATA_TABLE_DEFAULT_PAGE_SIZE,
    DATA_TABLE_PAGE_SIZE_OPTIONS,
    type DataTablePageSize,
} from "../../components/data-table-constants";

export type EvalReportsSortBy =
    | "audience"
    | "case_count"
    | "concurrency"
    | "generated_at"
    | "pass_threshold"
    | "repeats"
    | "run_count"
    | "status"
    | "suite"
    | "title";

export interface EvalReportsSearch {
    desc: boolean;
    page: number;
    pageSize: DataTablePageSize;
    query: string;
    report: string | undefined;
    sortBy: EvalReportsSortBy;
}

const DEFAULT_PAGE = 1;
const DEFAULT_PAGE_SIZE: EvalReportsSearch["pageSize"] =
    DATA_TABLE_DEFAULT_PAGE_SIZE;

export const DEFAULT_EVAL_REPORTS_SEARCH = {
    desc: true,
    page: DEFAULT_PAGE,
    pageSize: DEFAULT_PAGE_SIZE,
    query: "",
    report: undefined,
    sortBy: "generated_at",
} satisfies EvalReportsSearch;

const parsePositiveInt = (value: unknown): number | undefined => {
    if (typeof value === "number" && Number.isInteger(value) && value > 0) {
        return value;
    }

    if (typeof value !== "string") {
        return undefined;
    }

    const parsed = Number.parseInt(value, 10);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
};

const parseBoolean = (value: unknown): boolean | undefined => {
    if (typeof value === "boolean") {
        return value;
    }

    if (value === "true") {
        return true;
    }

    if (value === "false") {
        return false;
    }

    return undefined;
};

const parsePageSize = (
    value: unknown,
): EvalReportsSearch["pageSize"] | undefined => {
    const parsed = parsePositiveInt(value);
    return DATA_TABLE_PAGE_SIZE_OPTIONS.find((option) => option === parsed);
};

export const isEvalReportsSortBy = (
    value: unknown,
): value is EvalReportsSortBy =>
    value === "audience" ||
    value === "case_count" ||
    value === "concurrency" ||
    value === "generated_at" ||
    value === "pass_threshold" ||
    value === "repeats" ||
    value === "run_count" ||
    value === "status" ||
    value === "suite" ||
    value === "title";

const parseSortBy = (value: unknown): EvalReportsSortBy =>
    isEvalReportsSortBy(value) ? value : "generated_at";

export const validateEvalReportsSearch = (
    search: Record<string, unknown>,
): EvalReportsSearch => ({
    desc: parseBoolean(search.desc) ?? DEFAULT_EVAL_REPORTS_SEARCH.desc,
    page: parsePositiveInt(search.page) ?? DEFAULT_EVAL_REPORTS_SEARCH.page,
    pageSize:
        parsePageSize(search.pageSize) ?? DEFAULT_EVAL_REPORTS_SEARCH.pageSize,
    query:
        typeof search.query === "string"
            ? search.query
            : DEFAULT_EVAL_REPORTS_SEARCH.query,
    report:
        typeof search.report === "string" && search.report !== ""
            ? search.report
            : undefined,
    sortBy: parseSortBy(search.sortBy),
});
