export type MessageSourceUsage =
    | "search"
    | "lookup"
    | "retrieved_by_id"
    | "prompt";
export type GroundingSourceStatus = "pending" | "selected" | "no_selection";

export interface MessageSourceUsed {
    key: string;
    type:
        | "website_page"
        | "website_program"
        | "catalog_page"
        | "catalog_program"
        | "catalog_course"
        | "training_material"
        | "canned_response";
    id: number;
    title: string;
    url: string;
    usage: MessageSourceUsage;
    tool_call_id: string;
    tool_name: string;
    search_query?: string | null;
    chunk?: string | null;
    explanation?: string | null;
}

export interface ChatMessage {
    id: string;
    role: "user" | "assistant";
    content: string;
    timestamp: number;
    isLoading?: boolean;
    toolSourcesUsed?: MessageSourceUsed[];
    groundingSourcesUsed?: MessageSourceUsed[];
    groundingSourceStatus?: GroundingSourceStatus | null;
}

export type LoadingActivityStatus = "in_progress" | "complete" | "error";

export type LoadingActivityKind = "agent" | "tool" | "thinking";

export type LoadingToolState =
    | "input-streaming"
    | "input-available"
    | "approval-requested"
    | "approval-responded"
    | "output-available"
    | "output-error"
    | "output-denied";

export interface LoadingActivityItem {
    id: string;
    label: string;
    status: LoadingActivityStatus;
    parentId?: string;
    kind?: LoadingActivityKind;
    toolState?: LoadingToolState;
    toolName?: string;
    toolInput?: unknown;
    toolOutput?: unknown;
    toolErrorText?: string;
    thinkingContent?: string;
}

export interface LoadingActivityLogEntry {
    id: string;
    sequence: number;
    label: string;
    status: LoadingActivityStatus;
    parentId?: string;
    kind?: LoadingActivityKind;
    toolState?: LoadingToolState;
    toolName?: string;
    toolInput?: unknown;
    toolOutput?: unknown;
    toolErrorText?: string;
    thinkingContent?: string;
    startedAtMs?: number;
    durationMs?: number;
}

export interface LoadingIndicatorProps {
    isVisible: boolean;
    onTextShow?: () => void;
    messages?: string[];
    activityItems?: LoadingActivityItem[];
    activityLog?: LoadingActivityLogEntry[];
    variant?: "default" | "shimmer" | "ai-elements";
    showHeader?: boolean;
    forceOpenReasoning?: boolean;
    showEmptyState?: boolean;
}
