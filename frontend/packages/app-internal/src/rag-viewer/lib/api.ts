import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type {
    RagChunkListResponse,
    RagChunkSortBy,
    RagDocumentDetailData,
    RagDocumentExclusionEventFilter,
    RagDocumentExclusionEventListResponse,
    RagDocumentExclusionPayload,
    RagDocumentFileExtensionResponse,
    RagDocumentListResponse,
    RagDocumentSimilaritySearchResponse,
    RagDocumentSortBy,
    RagDocumentTreeNode,
    RagSourceType,
} from "../types";
import type { RagViewerExclusionFilter } from "./search-state";

interface FetchRagDocumentsParams {
    limit: number;
    offset: number;
    search?: string;
    searchMode: "exact" | "full_text";
    sortBy: RagDocumentSortBy;
    descending: boolean;
    types?: RagSourceType[];
    fileExtension?: string;
    exclusion?: RagViewerExclusionFilter;
}

export const fetchRagDocuments = async (
    api: AuthenticatedApi,
    {
        limit,
        offset,
        search,
        searchMode,
        sortBy,
        descending,
        types,
        fileExtension,
        exclusion,
    }: FetchRagDocumentsParams,
): Promise<RagDocumentListResponse> => {
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    params.set("search_mode", searchMode);
    params.set("sort_by", sortBy);
    params.set("descending", String(descending));

    if (search !== undefined && search.trim() !== "") {
        params.set("search", search.trim());
    }

    if (types !== undefined && types.length > 0) {
        for (const type of types) {
            params.append("types", type);
        }
    }

    if (fileExtension !== undefined && fileExtension.trim() !== "") {
        params.set("file_extension", fileExtension.trim());
    }

    if (exclusion !== undefined) {
        params.set("exclusion", exclusion);
    }

    return api.get<RagDocumentListResponse>(
        `/rag/documents?${params.toString()}`,
    );
};

export const fetchRagDocument = async (
    api: AuthenticatedApi,
    documentId: string,
): Promise<RagDocumentDetailData> =>
    api.get<RagDocumentDetailData>(
        `/rag/documents/${encodeURIComponent(documentId)}`,
    );

export const fetchRagDocumentTree = async (
    api: AuthenticatedApi,
    exclusion: RagViewerExclusionFilter = "all",
): Promise<RagDocumentTreeNode[]> =>
    api.get<RagDocumentTreeNode[]>(
        `/rag/documents/tree?exclusion=${encodeURIComponent(exclusion)}`,
    );

export const fetchRagDocumentFileExtensions = async (
    api: AuthenticatedApi,
): Promise<RagDocumentFileExtensionResponse> =>
    api.get<RagDocumentFileExtensionResponse>("/rag/documents/file-extensions");

interface FetchRagDocumentExclusionEventsParams {
    limit: number;
    offset: number;
    search?: string;
    action?: RagDocumentExclusionEventFilter;
    types?: RagSourceType[];
    sortBy?: string;
    descending?: boolean;
}

export const fetchRagDocumentExclusionEvents = async (
    api: AuthenticatedApi,
    {
        limit,
        offset,
        search,
        action,
        types,
        sortBy,
        descending,
    }: FetchRagDocumentExclusionEventsParams,
): Promise<RagDocumentExclusionEventListResponse> => {
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    if (sortBy !== undefined) {
        params.set("sort_by", sortBy);
    }
    if (descending !== undefined) {
        params.set("descending", String(descending));
    }

    if (search !== undefined && search.trim() !== "") {
        params.set("search", search.trim());
    }

    if (action !== undefined) {
        params.set("action", action);
    }

    if (types !== undefined && types.length > 0) {
        for (const type of types) {
            params.append("types", type);
        }
    }

    return api.get<RagDocumentExclusionEventListResponse>(
        `/rag/documents/exclusion-events?${params.toString()}`,
    );
};

interface SearchRagDocumentChunksBySimilarityParams {
    limit: number;
    query: string;
    types?: RagSourceType[];
    fileExtension?: string;
    exclusion?: RagViewerExclusionFilter;
}

export const searchRagDocumentChunksBySimilarity = async (
    api: AuthenticatedApi,
    {
        limit,
        query,
        types,
        fileExtension,
        exclusion,
    }: SearchRagDocumentChunksBySimilarityParams,
): Promise<RagDocumentSimilaritySearchResponse> => {
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    params.set("query", query.trim());

    if (types !== undefined && types.length > 0) {
        for (const type of types) {
            params.append("types", type);
        }
    }

    if (fileExtension !== undefined && fileExtension.trim() !== "") {
        params.set("file_extension", fileExtension.trim());
    }

    if (exclusion !== undefined) {
        params.set("exclusion", exclusion);
    }

    return api.get<RagDocumentSimilaritySearchResponse>(
        `/rag/documents/similarity?${params.toString()}`,
    );
};

interface FetchRagChunksParams {
    limit: number;
    offset: number;
    search?: string;
    sortBy: RagChunkSortBy;
    descending: boolean;
    types?: RagSourceType[];
    fileExtension?: string;
    exclusion?: RagViewerExclusionFilter;
}

export const fetchRagChunks = async (
    api: AuthenticatedApi,
    {
        limit,
        offset,
        search,
        sortBy,
        descending,
        types,
        fileExtension,
        exclusion,
    }: FetchRagChunksParams,
): Promise<RagChunkListResponse> => {
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    params.set("sort_by", sortBy);
    params.set("descending", String(descending));

    if (search !== undefined && search.trim() !== "") {
        params.set("search", search.trim());
    }

    if (types !== undefined && types.length > 0) {
        for (const type of types) {
            params.append("types", type);
        }
    }

    if (fileExtension !== undefined && fileExtension.trim() !== "") {
        params.set("file_extension", fileExtension.trim());
    }

    if (exclusion !== undefined) {
        params.set("exclusion", exclusion);
    }

    return api.get<RagChunkListResponse>(
        `/rag/documents/chunks?${params.toString()}`,
    );
};

export const excludeRagDocument = async (
    api: AuthenticatedApi,
    payload: RagDocumentExclusionPayload,
): Promise<void> => {
    await api.put("/rag/documents/exclusion", payload);
};

export const includeRagDocument = async (
    api: AuthenticatedApi,
    sourceKey: string,
): Promise<void> => {
    const params = new URLSearchParams();
    params.set("source_key", sourceKey);
    await api.delete(`/rag/documents/exclusion?${params.toString()}`);
};
