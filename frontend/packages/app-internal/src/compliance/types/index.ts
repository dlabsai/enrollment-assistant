// API boundary types: nullable fields mirror the server; local optional state uses undefined.
export interface InstructionsVersion {
    id: string;
    number: number;
    created_at: string;
    author: string;
}
export interface InstructionsDetail extends InstructionsVersion {
    content: string;
}
export interface InstructionsPage {
    current: InstructionsDetail | null;
    versions: InstructionsVersion[];
    total: number;
}
export interface Period {
    start: string;
    end: string;
}
export interface Preview {
    messages: number;
    conversations: number;
    max_messages: number;
    instructions: InstructionsVersion | null;
    overlaps: { id: string; created_at: string }[];
    worker_enabled: boolean;
}
export interface ScreeningSummary {
    id: string;
    created_at: string;
    author: string;
    start: string;
    end: string;
    instructions_version_id: string;
    admission_error: string | null;
    messages: number;
    conversations: number;
    screened: number;
    screened_conversations: number;
    pending: number;
    errors: number;
    error_conversations: number;
    deleted: number;
    findings: number;
    needs_review: number;
}
interface ScreeningFailure {
    chat_id: string;
    chat: string;
    assistant_messages: number;
    reason: string;
    retryable: boolean;
}
export interface ScreeningDetail extends ScreeningSummary {
    instructions: InstructionsDetail;
    failures: ScreeningFailure[];
}
export interface ScreeningsPage {
    items: ScreeningSummary[];
    total: number;
}
export type DecisionState = "confirmed" | "dismissed";
export type ReviewState = "needs_review" | DecisionState;
export type FindingCategory =
    | "inappropriate"
    | "misinformation"
    | "regulatory_compliance"
    | "reputation_risk"
    | "confidentiality";
export interface FlagSummary {
    id: string;
    title: string;
    categories: FindingCategory[] | null;
    chat: string;
    message_at: string;
    state: ReviewState;
}
export interface FlagsPage {
    items: FlagSummary[];
    total: number;
}
export interface Decision {
    state: DecisionState;
    comment: string | null;
    reviewer: string;
    created_at: string;
    revision: number;
}
export interface Finding {
    id: string;
    title: string;
    categories: FindingCategory[] | null;
    explanation: string;
    evidence: string;
    state: ReviewState;
    revision: number;
    decisions: Decision[];
}
export interface FlagDetail {
    chat: string;
    message_id: string;
    message_at: string;
    error: string | null;
    transcript: {
        id: string;
        parent_id: string | null;
        role: "user" | "assistant";
        content: string;
        created_at: string;
    }[];
    flag: Finding | null;
}
