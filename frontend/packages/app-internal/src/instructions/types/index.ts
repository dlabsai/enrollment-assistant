export interface PromptFile {
    filename: string;
    content: string;
}

interface PromptTemplate {
    id: string;
    filename: string;
    content: string;
}

export type PromptSetScope =
    | "assistant"
    | "investigation"
    | "summary"
    | "title"
    | "title_transcript"
    | "grounding";

export interface PromptSetVersion {
    id: string;
    version_number: number;
    name: string;
    description?: string;
    is_internal: boolean;
    scope: PromptSetScope;
    is_deployed: boolean;
    created_by_id: string;
    created_by_name: string;
    created_at: string;
    prompts: PromptTemplate[];
}

export interface PromptSetVersionListItem {
    id: string;
    version_number: number;
    name: string;
    description?: string;
    is_internal: boolean;
    scope: PromptSetScope;
    is_deployed: boolean;
    created_by_id: string;
    created_by_name: string;
    created_at: string;
    modified_prompt_count: number;
}

export interface ActiveVersion {
    id?: string;
    version_number?: number;
    name?: string;
}

export interface PromptSetVersionCreate {
    name: string;
    description?: string;
    is_internal: boolean;
    scope: PromptSetScope;
    prompts: { filename: string; content: string }[];
}

export type InstructionsTab = "editor" | "test-chat";

export type ConfirmDialogAction =
    | "delete-version"
    | "switch-version"
    | "select-default"
    | "reset-template";
