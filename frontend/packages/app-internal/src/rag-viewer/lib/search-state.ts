import {
    DATA_TABLE_DEFAULT_PAGE_SIZE,
    type DataTablePageSize,
    isDataTablePageSize,
} from "../../components/data-table-constants";
import type { RagDocumentListSortBy, RagSourceType } from "../types";

export type RagViewerSourceFilter =
    | RagSourceType
    | "all"
    | "website"
    | "catalog"
    | "training";
export type RagViewerExclusionFilter = "all" | "included" | "excluded";
type RagViewerSearchMode = "exact" | "full_text" | "similarity";

export interface RagViewerSearch {
    document: string | undefined;
    query: string;
    fileExtension: string;
    searchMode: RagViewerSearchMode;
    source: RagViewerSourceFilter;
    exclusion: RagViewerExclusionFilter;
    sortBy: RagDocumentListSortBy;
    desc: boolean;
    page: number;
    pageSize: DataTablePageSize;
}

const isSortBy = (value: string): value is RagDocumentListSortBy =>
    value === "modified_at" ||
    value === "created_at" ||
    value === "title" ||
    value === "url" ||
    value === "source_type" ||
    value === "source_id" ||
    value === "token_count" ||
    value === "character_count" ||
    value === "chunk_count";

export const isRagViewerSourceFilter = (
    value: string,
): value is RagViewerSourceFilter =>
    value === "all" ||
    value === "website" ||
    value === "catalog" ||
    value === "training" ||
    value === "website_page" ||
    value === "website_program" ||
    value === "catalog_page" ||
    value === "catalog_program" ||
    value === "catalog_course" ||
    value === "training_material";

export const isRagViewerExclusionFilter = (
    value: string,
): value is RagViewerExclusionFilter =>
    value === "all" || value === "included" || value === "excluded";

const isSearchMode = (value: string): value is RagViewerSearchMode =>
    value === "exact" || value === "full_text" || value === "similarity";

const parseSearchMode = (value: unknown): RagViewerSearchMode => {
    if (typeof value !== "string") {
        return "exact";
    }

    if (value === "text") {
        return "exact";
    }

    return isSearchMode(value) ? value : "exact";
};

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

const parseDescending = (value: unknown): boolean | undefined => {
    if (typeof value === "boolean") {
        return value;
    }

    if (typeof value !== "string") {
        return undefined;
    }

    if (value === "true") {
        return true;
    }

    if (value === "false") {
        return false;
    }

    return undefined;
};

const parseFileExtension = (value: unknown): string => {
    if (typeof value !== "string") {
        return "";
    }

    let normalized = value.trim().toLowerCase();
    while (normalized.startsWith(".")) {
        normalized = normalized.slice(1);
    }

    if (!/^[\da-z]+$/u.test(normalized)) {
        return "";
    }

    return normalized;
};

export const validateRagViewerSearch = (
    search: Record<string, unknown>,
): RagViewerSearch => {
    const pageSize = parsePositiveInt(search.pageSize);

    return {
        document:
            typeof search.document === "string" && search.document !== ""
                ? search.document
                : undefined,
        query: typeof search.query === "string" ? search.query : "",
        fileExtension: parseFileExtension(search.fileExtension),
        searchMode: parseSearchMode(search.searchMode),
        source:
            typeof search.source === "string" &&
            isRagViewerSourceFilter(search.source)
                ? search.source
                : "all",
        exclusion:
            typeof search.exclusion === "string" &&
            isRagViewerExclusionFilter(search.exclusion)
                ? search.exclusion
                : "all",
        sortBy:
            typeof search.sortBy === "string" && isSortBy(search.sortBy)
                ? search.sortBy
                : "modified_at",
        desc: parseDescending(search.desc) ?? true,
        page: parsePositiveInt(search.page) ?? 1,
        pageSize: isDataTablePageSize(pageSize)
            ? pageSize
            : DATA_TABLE_DEFAULT_PAGE_SIZE,
    };
};
