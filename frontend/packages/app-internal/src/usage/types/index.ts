export interface UsageTraceBasic {
    created_at: string;
    model: string;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    cost: number | null;
    duration: number | null;
    is_error: boolean;
    is_public: boolean | null;
}

export interface UsageDaily {
    date: string;
    requests: number;
    tokens: number;
    cost: number;
    embeddingRequests: number;
    embeddingTokens: number;
    embeddingCost: number;
    errors: number;
    avgDuration: number;
}

export interface ModelUsage {
    model: string;
    requests: number;
    tokens: number;
    cost: number;
}

export interface UsageSummary {
    totalRequests: number;
    totalTokens: number;
    totalCost: number;
    totalEmbeddingRequests: number;
    totalEmbeddingTokens: number;
    totalEmbeddingCost: number;
    totalEmbeddingAvgDuration: number;
    totalErrors: number;
    avgDuration: number;
}

export interface UsageDailyApi {
    date: string;
    requests: number;
    tokens: number;
    cost: number;
    embedding_requests: number;
    embedding_tokens: number;
    embedding_cost: number;
    errors: number;
    avg_duration: number | null;
}

export interface UsageModelApi {
    model: string;
    requests: number;
    tokens: number;
    cost: number;
}

export interface UsageSummaryApi {
    total_requests: number;
    total_tokens: number;
    total_cost: number;
    total_embedding_requests: number;
    total_embedding_tokens: number;
    total_embedding_cost: number;
    total_embedding_avg_duration: number | null;
    total_errors: number;
    avg_duration: number | null;
}

export interface UsageOverviewApi {
    summary: UsageSummaryApi;
    daily: UsageDailyApi[];
    models: UsageModelApi[];
    latest_traces: UsageTraceBasic[];
}

export interface ChatAnalyticsDaily {
    date: string;
    conversations: number;
    messages: number;
    avg_messages_per_conversation: number;
    single_message_rate: number;
}

export interface ChatAnalyticsBucket {
    label: string;
    conversations: number;
}

export interface ChatAnalyticsHourly {
    hour: number;
    messages: number;
}

export interface ChatAnalyticsStats {
    min: number | null;
    p50: number | null;
    median: number | null;
    avg: number | null;
    p75: number | null;
    p90: number | null;
    p95: number | null;
    p99: number | null;
    max: number | null;
}

export interface ChatAnalyticsResponseTimeBucket {
    label: string;
    responses: number;
}

export interface ChatAnalyticsSummary {
    total_conversations: number;
    total_messages: number;
    avg_messages_per_conversation: number;
    single_message_rate: number;
    daily: ChatAnalyticsDaily[];
    length_buckets: ChatAnalyticsBucket[];
    hourly_activity: ChatAnalyticsHourly[];
    length_stats: ChatAnalyticsStats | null;
    response_time_buckets: ChatAnalyticsResponseTimeBucket[];
    response_time_stats: ChatAnalyticsStats | null;
}

export interface PublicUsageDaily {
    date: string;
    conversations: number;
    messages: number;
    avg_messages_per_conversation: number;
    drop_off_rate: number;
    leads: number;
}

export interface PublicUsageSummary {
    total_conversations: number;
    total_messages: number;
    avg_messages_per_conversation: number;
    drop_off_rate: number;
    total_leads: number;
    lead_capture_rate: number;
    daily: PublicUsageDaily[];
    depth_buckets: PublicUsageBucket[];
    hourly_activity: PublicUsageHourly[];
}

export interface PublicUsageBucket {
    label: string;
    conversations: number;
}

export interface PublicUsageHourly {
    hour: number;
    messages: number;
}
