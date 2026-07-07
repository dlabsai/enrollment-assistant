export interface MessageListRow {
    id: string;
    conversationId: string;
    role: string;
    content: string;
    contentPreview: string;
    contentLength: number;
    conversationTitle?: string;
    conversationSummary?: string;
    isPublic: boolean;
    conversationUserName?: string;
    conversationUserEmail?: string;
    generationTimeMs?: number;
    inputTokens?: number;
    outputTokens?: number;
    toolCallCount: number;
    guardrailFailureCount: number;
    guardrailsBlocked: boolean;
    traceId?: string;
    spanId?: string;
    createdAt: string;
    updatedAt: string;
}

export interface MessageListPage {
    items: MessageListRow[];
    total: number;
}
