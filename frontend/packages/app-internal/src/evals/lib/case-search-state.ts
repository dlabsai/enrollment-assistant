import {
    DATA_TABLE_DEFAULT_PAGE_SIZE,
    DATA_TABLE_PAGE_SIZE_OPTIONS,
    type DataTablePageSize,
} from "../../components/data-table-constants";
import type { EvalSuite } from "../types";

export type EvalCasesSortBy = "case_id" | "message" | "expected" | "criteria";

export interface EvalCasesSearch {
    caseId: string | undefined;
    desc: boolean;
    page: number;
    pageSize: DataTablePageSize;
    query: string;
    sortBy: EvalCasesSortBy;
    suite: EvalSuite;
}

const DEFAULT_PAGE = 1;
const DEFAULT_PAGE_SIZE: EvalCasesSearch["pageSize"] =
    DATA_TABLE_DEFAULT_PAGE_SIZE;

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
): EvalCasesSearch["pageSize"] | undefined => {
    const parsed = parsePositiveInt(value);
    return DATA_TABLE_PAGE_SIZE_OPTIONS.find((option) => option === parsed);
};

export const isEvalCasesSortBy = (value: unknown): value is EvalCasesSortBy =>
    value === "case_id" ||
    value === "message" ||
    value === "expected" ||
    value === "criteria";

const parseSortBy = (value: unknown): EvalCasesSortBy =>
    isEvalCasesSortBy(value) ? value : "case_id";

const parseSuite = (value: unknown): EvalSuite =>
    value === "guardrails" ? "guardrails" : "chatbot";

export const validateEvalCasesSearch = (
    search: Record<string, unknown>,
): EvalCasesSearch => ({
    caseId:
        typeof search.caseId === "string" && search.caseId !== ""
            ? search.caseId
            : undefined,
    desc: parseBoolean(search.desc) ?? false,
    page: parsePositiveInt(search.page) ?? DEFAULT_PAGE,
    pageSize: parsePageSize(search.pageSize) ?? DEFAULT_PAGE_SIZE,
    query: typeof search.query === "string" ? search.query : "",
    sortBy: parseSortBy(search.sortBy),
    suite: parseSuite(search.suite),
});
