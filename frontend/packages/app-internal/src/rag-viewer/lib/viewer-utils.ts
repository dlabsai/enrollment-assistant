import { makeLocaleNumberFormatter } from "../../lib/number-format";
import type {
    RagChunkSortBy,
    RagDocumentListSortBy,
    RagSourceType,
} from "../types";
import type {
    RagViewerExclusionFilter,
    RagViewerSourceFilter,
} from "./search-state";

const WEBSITE_SOURCE_TYPES: RagSourceType[] = ["website_page", "website_program"];
const CATALOG_SOURCE_TYPES: RagSourceType[] = [
    "catalog_page",
    "catalog_program",
    "catalog_course",
];
const TRAINING_SOURCE_TYPES: RagSourceType[] = ["training_material"];

export const SOURCE_FILTER_OPTIONS: {
    label: string;
    value: RagViewerSourceFilter;
}[] = [
    { label: "All document types", value: "all" },
    { label: "Website only", value: "website" },
    { label: "Catalog only", value: "catalog" },
    { label: "Training materials only", value: "training" },
    { label: "Website pages", value: "website_page" },
    { label: "Website programs", value: "website_program" },
    { label: "Catalog pages", value: "catalog_page" },
    { label: "Catalog programs", value: "catalog_program" },
    { label: "Catalog courses", value: "catalog_course" },
    { label: "Training materials", value: "training_material" },
];

export const EXCLUSION_FILTER_OPTIONS: {
    label: string;
    value: RagViewerExclusionFilter;
}[] = [
    { label: "All statuses", value: "all" },
    { label: "Included only", value: "included" },
    { label: "Excluded only", value: "excluded" },
];

export const SORT_OPTIONS: { label: string; value: RagDocumentListSortBy }[] = [
    { label: "Modified", value: "modified_at" },
    { label: "Created", value: "created_at" },
    { label: "Token count", value: "token_count" },
    { label: "Character count", value: "character_count" },
    { label: "Chunk count", value: "chunk_count" },
    { label: "Name", value: "title" },
    { label: "Type", value: "source_type" },
    { label: "ID", value: "source_id" },
    { label: "URL", value: "url" },
];

export const CHUNK_SORT_OPTIONS: { label: string; value: RagChunkSortBy }[] = [
    { label: "Modified", value: "modified_at" },
    { label: "Created", value: "created_at" },
    { label: "Name", value: "title" },
    { label: "Type", value: "source_type" },
    { label: "ID", value: "source_id" },
    { label: "Token count", value: "token_count" },
    { label: "Character count", value: "character_count" },
];

export const getChunkSortBy = (
    sortBy: RagDocumentListSortBy,
): RagChunkSortBy => {
    if (
        sortBy === "modified_at" ||
        sortBy === "created_at" ||
        sortBy === "title" ||
        sortBy === "source_type" ||
        sortBy === "source_id" ||
        sortBy === "token_count" ||
        sortBy === "character_count"
    ) {
        return sortBy;
    }

    return "character_count";
};

export const SEARCH_MODE_HELP_ITEMS = [
    {
        label: "Exact text",
        description:
            "Matches the typed characters case-insensitively, like a literal phrase or substring.",
    },
    {
        label: "Full text",
        description:
            "Uses web-style keyword search: unquoted words are combined, quoted phrases stay phrase-like, OR broadens results, and minus excludes terms; results are relevance-ranked.",
    },
    {
        label: "Semantic",
        description:
            "Searches document chunks by meaning, so useful matches can appear without exact wording.",
    },
] as const;

const numberFormatter = makeLocaleNumberFormatter();
const similarityFormatter = makeLocaleNumberFormatter({
    maximumFractionDigits: 3,
    minimumFractionDigits: 3,
});

export const formatNumber = (value: number): string =>
    numberFormatter.format(value);
export const formatSimilarity = (value: number): string =>
    similarityFormatter.format(value);

export const l2DistanceToApproxCosineSimilarity = (distance: number): number =>
    Math.max(-1, Math.min(1, 1 - (distance * distance) / 2));

export type MarkdownViewMode = "rendered" | "source";
export type RagViewerLeftTab = "search" | "chunks" | "tree";

export const SHOW_CHUNKS_PANE_STORAGE_KEY = "rag-viewer-show-chunks-pane";
export const EXPAND_ALL_CHUNKS_STORAGE_KEY = "rag-viewer-expand-all-chunks";
export const MARKDOWN_VIEW_MODE_STORAGE_KEY = "rag-viewer-markdown-view-mode";
export const LARGE_MARKDOWN_RENDER_CHARACTER_THRESHOLD = 100_000;

export const getStoredBooleanPreference = (
    key: string,
    defaultValue: boolean,
): boolean => {
    if (typeof window === "undefined") {
        return defaultValue;
    }

    const stored = window.localStorage.getItem(key);
    if (stored === null) {
        return defaultValue;
    }

    return stored === "true";
};

export const getStoredMarkdownViewMode = (): MarkdownViewMode => {
    if (typeof window === "undefined") {
        return "rendered";
    }

    const stored = window.localStorage.getItem(MARKDOWN_VIEW_MODE_STORAGE_KEY);
    return stored === "source" ? "source" : "rendered";
};

export const getSourceTypesForFilter = (
    sourceFilter: RagViewerSourceFilter,
): RagSourceType[] | undefined => {
    if (sourceFilter === "all") {
        return undefined;
    }

    if (sourceFilter === "website") {
        return WEBSITE_SOURCE_TYPES;
    }

    if (sourceFilter === "catalog") {
        return CATALOG_SOURCE_TYPES;
    }

    if (sourceFilter === "training") {
        return TRAINING_SOURCE_TYPES;
    }

    return [sourceFilter];
};

export const getSourceLabel = (sourceType: RagSourceType): string => {
    switch (sourceType) {
        case "website_page": {
            return "Website page";
        }
        case "website_program": {
            return "Website program";
        }
        case "catalog_page": {
            return "Catalog page";
        }
        case "catalog_program": {
            return "Catalog program";
        }
        case "catalog_course": {
            return "Catalog course";
        }
        case "training_material": {
            return "Training material";
        }
        default: {
            const exhaustiveCheck: never = sourceType;
            return exhaustiveCheck;
        }
    }
};

export { formatTableTimestamp as formatTimestamp } from "../../lib/date-format";
