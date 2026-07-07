export type PermissionKey =
    | "access_chats"
    | "access_investigations"
    | "access_messages"
    | "access_instructions"
    | "access_traces"
    | "access_rag"
    | "access_rbac"
    | "access_usage"
    | "access_analytics"
    | "access_public_analytics"
    | "access_evals"
    | "access_settings"
    | "access_rag_viewer"
    | "access_rag_exclusions"
    | "chat_regenerate"
    | "chat_view_activity"
    | "chat_view_trace"
    | "chat_model_selection"
    | "chat_duration_tooltip"
    | "chat_view_response_cost"
    | "chat_view_guardrails_failures"
    | "chat_view_sources"
    | "chat_view_tools"
    | "chats_view_own"
    | "chats_view_users"
    | "chats_view_admins"
    | "chats_view_devs"
    | "chats_view_trace"
    | "chats_view_cost_column";

export interface UserGroup {
    id: string;
    slug: "user" | "admin" | "dev";
    name: string;
}

export interface UserProfile {
    id: string;
    email: string;
    name: string;
    group: UserGroup;
    permissions: Record<PermissionKey, boolean>;
    is_active: boolean;
    created_at: string;
    updated_at: string;
}
