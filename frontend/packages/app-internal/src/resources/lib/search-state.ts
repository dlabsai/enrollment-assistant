import {
    DATA_TABLE_DEFAULT_PAGE_SIZE,
    type DataTablePageSize,
    isDataTablePageSize,
} from "../../components/data-table-constants";
import {
    isRagViewerExclusionFilter,
    isRagViewerSourceFilter,
    type RagViewerExclusionFilter,
    type RagViewerSourceFilter,
} from "../../rag-viewer/lib/search-state";
import type {
    RagDocumentExclusionEventSortBy,
    RagDocumentSortBy,
} from "../../rag-viewer/types";

export type ResourcesView = "list" | "folders" | "history";
export type ResourcesSortBy =
    | Extract<
          RagDocumentSortBy,
          "title" | "source_type" | "source_id" | "excluded"
      >
    | RagDocumentExclusionEventSortBy;

export interface ResourcesSearch {
    document: string | undefined;
    view: ResourcesView;
    query: string;
    exclusion: RagViewerExclusionFilter;
    source: RagViewerSourceFilter;
    sortBy: ResourcesSortBy;
    desc: boolean;
    page: number;
    pageSize: DataTablePageSize;
}

const DEFAULT_EXCLUSION: RagViewerExclusionFilter = "all";
const DEFAULT_PAGE = 1;
const DEFAULT_PAGE_SIZE: ResourcesSearch["pageSize"] =
    DATA_TABLE_DEFAULT_PAGE_SIZE;
const DEFAULT_QUERY = "";
const DEFAULT_SOURCE: RagViewerSourceFilter = "all";

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

const parseView = (value: unknown): ResourcesView => {
    if (value === "folders" || value === "browse") {
        return "folders";
    }

    if (value === "history") {
        return "history";
    }

    return "list";
};

const parsePageSize = (
    value: unknown,
): ResourcesSearch["pageSize"] | undefined => {
    const parsed = parsePositiveInt(value);
    return isDataTablePageSize(parsed) ? parsed : undefined;
};

export const isResourcesListSortBy = (
    value: unknown,
): value is Extract<
    RagDocumentSortBy,
    "title" | "source_type" | "source_id" | "excluded"
> =>
    value === "title" ||
    value === "source_type" ||
    value === "source_id" ||
    value === "excluded";

export const isResourcesHistorySortBy = (
    value: unknown,
): value is RagDocumentExclusionEventSortBy =>
    value === "created_at" ||
    value === "action" ||
    value === "document_title" ||
    value === "source_type" ||
    value === "actor";

export const defaultResourcesSortBy = (
    view: ResourcesView,
): ResourcesSortBy => (view === "history" ? "created_at" : "title");

export const defaultResourcesDescending = (view: ResourcesView): boolean =>
    view === "history";

const parseSortBy = (
    value: unknown,
    view: ResourcesView,
): ResourcesSortBy => {
    if (view === "history") {
        return isResourcesHistorySortBy(value) ? value : "created_at";
    }
    return isResourcesListSortBy(value) ? value : "title";
};

export const validateResourcesSearch = (
    search: Record<string, unknown>,
): ResourcesSearch => {
    const view = parseView(search.view);

    return {
        document:
            typeof search.document === "string" && search.document !== ""
                ? search.document
                : undefined,
        desc: parseBoolean(search.desc) ?? defaultResourcesDescending(view),
        exclusion:
            typeof search.exclusion === "string" &&
            isRagViewerExclusionFilter(search.exclusion)
                ? search.exclusion
                : DEFAULT_EXCLUSION,
        page: parsePositiveInt(search.page) ?? DEFAULT_PAGE,
        pageSize: parsePageSize(search.pageSize) ?? DEFAULT_PAGE_SIZE,
        query: typeof search.query === "string" ? search.query : DEFAULT_QUERY,
        sortBy: parseSortBy(search.sortBy, view),
        source:
            typeof search.source === "string" &&
            isRagViewerSourceFilter(search.source)
                ? search.source
                : DEFAULT_SOURCE,
        view,
    };
};
