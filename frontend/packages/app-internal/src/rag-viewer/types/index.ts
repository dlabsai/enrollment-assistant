export type RagSourceType =
    | "website_page"
    | "website_program"
    | "catalog_page"
    | "catalog_program"
    | "catalog_course"
    | "training_material";

export type RagDocumentListSortBy =
    | "modified_at"
    | "created_at"
    | "title"
    | "url"
    | "source_type"
    | "source_id"
    | "token_count"
    | "character_count"
    | "chunk_count";

export type RagDocumentSortBy =
    | RagDocumentListSortBy
    | "source_key"
    | "excluded";

export type RagChunkSortBy = Extract<
    RagDocumentListSortBy,
    | "modified_at"
    | "created_at"
    | "title"
    | "source_type"
    | "source_id"
    | "token_count"
    | "character_count"
>;

export interface RagDocumentSummary {
    id: string;
    source_type: RagSourceType;
    source_id: number;
    title: string;
    url: string;
    token_count: number;
    character_count: number;
    chunk_count: number;
    source_key: string;
    excluded: boolean;
    exclusion_reason: string | null;
    created_at: string | null;
    modified_at: string | null;
}

export interface RagDocumentChunk {
    id: string;
    sequence_number: number;
    content: string;
    token_count: number;
    character_count: number;
    created_at: string;
    updated_at: string;
}

export interface RagDocumentDetailData extends RagDocumentSummary {
    markdown_content: string;
    chunks: RagDocumentChunk[];
}

export interface RagDocumentSimilarityMatch extends RagDocumentSummary {
    chunk_id: string;
    sequence_number: number;
    content: string;
    chunk_token_count: number;
    chunk_character_count: number;
    distance: number;
}

export interface RagDocumentTreeNode {
    id: string;
    label: string;
    document_id: string | null;
    source_type: RagSourceType | null;
    source_id: number | null;
    excluded: boolean;
    children: RagDocumentTreeNode[];
}

export interface RagDocumentExclusionSummary {
    documents: number;
    chunks: number;
    tokens: number;
}

export interface RagDocumentListResponse {
    items: RagDocumentSummary[];
    total: number;
    excluded: RagDocumentExclusionSummary;
}

export interface RagDocumentSimilaritySearchResponse {
    items: RagDocumentSimilarityMatch[];
    total: number;
}

export interface RagChunkListItem {
    id: string;
    sequence_number: number;
    content: string;
    token_count: number;
    character_count: number;
    created_at: string;
    updated_at: string;
    document: RagDocumentSummary;
}

export interface RagChunkListResponse {
    items: RagChunkListItem[];
    total: number;
}

export interface RagDocumentFileExtensionResponse {
    extensions: string[];
}

export interface RagDocumentExclusionPayload {
    source_key: string;
    reason: string;
}

export type RagDocumentExclusionEventAction = "excluded" | "included";
export type RagDocumentExclusionEventFilter =
    | "all"
    | RagDocumentExclusionEventAction;
export type RagDocumentExclusionEventSortBy =
    | "created_at"
    | "action"
    | "document_title"
    | "source_type"
    | "actor";

export interface RagDocumentExclusionEvent {
    id: string;
    source_key: string;
    action: RagDocumentExclusionEventAction;
    reason: string | null;
    document_title: string | null;
    document_url: string | null;
    source_type: RagSourceType | null;
    actor_name: string | null;
    actor_email: string | null;
    created_by_user_id: string | null;
    created_at: string;
    document_id: string | null;
}

export interface RagDocumentExclusionEventListResponse {
    items: RagDocumentExclusionEvent[];
    total: number;
}
