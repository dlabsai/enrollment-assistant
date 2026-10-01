import type { TimeGranularity } from "../../lib/time-series";

export interface ChatInsightRun {
    id: string;
    status: string;
    error_count: number;
    error_code: string | null;
}

export interface ChatInsightCoverage {
    analyzed_chats: number;
    classification_gaps: number;
    document_grounded_answers: number;
    referenced_documents: number;
    classified_documents: number;
}

interface NamedCount {
    key: string;
    name: string;
    answers: number;
}

export interface TopicMetric {
    key: string;
    name: string;
    description: string;
    primary_chats: number;
    mention_chats: number;
    top_document_subjects: NamedCount[];
    top_document_functions: NamedCount[];
}

export interface RequestTypeMetric {
    key: string;
    name: string;
    chats: number;
}

export interface TopicPairMetric {
    first_key: string;
    first_name: string;
    second_key: string;
    second_name: string;
    chats: number;
}

export interface SourceMetric {
    key: string;
    name: string;
    chats: number;
    answers: number;
    current_documents: number;
    current_documents_used: number;
    utilization: number | null;
}

export interface GroundedDocumentMetric {
    source_key: string;
    title: string;
    url: string;
    document_type: string;
    chats: number;
    answers: number;
    last_used_at: string;
    primary_subject: string | null;
    secondary_subjects: string[];
    document_function: string | null;
    confidence: string | null;
}

export interface TrendPoint {
    bucket_start: string;
    bucket_end: string;
    chats: number;
    answers: number;
}

export interface TrendRow {
    key: string;
    name: string;
    points: TrendPoint[];
}

export interface ChatInsightSummary {
    data_through: string | null;
    taxonomy_revision: number;
    latest_run: ChatInsightRun | null;
    coverage: ChatInsightCoverage;
    topics: TopicMetric[];
    request_types: RequestTypeMetric[];
    topic_pairs: TopicPairMetric[];
    sources: SourceMetric[];
    top_documents: GroundedDocumentMetric[];
    time_granularity: TimeGranularity;
    topic_trends: TrendRow[];
    source_trends: TrendRow[];
    document_trends: TrendRow[];
}

export interface ChatInsightCategory {
    key: string;
    name: string;
    description: string;
    include_examples: string[];
    exclude_examples: string[];
    origin: "system" | "client";
    active: boolean;
}

export interface ChatInsightCategoryList {
    published_revision: number;
    pending_revision: number | null;
    categories: ChatInsightCategory[];
}

export interface ChatInsightData {
    summary: ChatInsightSummary;
    categories: ChatInsightCategoryList;
}

export interface ChatInsightCategoryInput {
    name: string;
    description: string;
    include_examples: string[];
    exclude_examples: string[];
    active?: boolean;
}
