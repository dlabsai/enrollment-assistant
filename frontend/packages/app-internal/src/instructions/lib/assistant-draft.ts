import type { PromptFile } from "../types/index.ts";
import {
    getSectionIdForScope,
    getTemplateFilenamesForScope,
    INTERNAL_PROMPT_PLATFORM,
} from "./sections.ts";
import type { InstructionsStoreState } from "./store.ts";

const ASSISTANT_SECTION_ID = getSectionIdForScope(
    "assistant",
    INTERNAL_PROMPT_PLATFORM,
);

const ASSISTANT_TEMPLATE_FILENAMES = getTemplateFilenamesForScope(
    "assistant",
    INTERNAL_PROMPT_PLATFORM,
);

type AssistantDraftState = Pick<
    InstructionsStoreState,
    | "activeSectionId"
    | "diskTemplates"
    | "drafts"
    | "isDefaultSelected"
    | "isDefaultSelectedBySection"
    | "selectedVersionDetail"
    | "selectedVersionId"
    | "selectedVersionIdBySection"
>;

export const selectHasAssistantDraft = (
    state: AssistantDraftState,
): boolean =>
    ASSISTANT_TEMPLATE_FILENAMES.some(
        (filename) => state.drafts[filename] !== undefined,
    );

export const selectAssistantDraftBaseVersionId = (
    state: AssistantDraftState,
): string | undefined => {
    const storedDefault = state.isDefaultSelectedBySection[ASSISTANT_SECTION_ID];
    const isActiveAssistantSection =
        state.activeSectionId === ASSISTANT_SECTION_ID;
    const isDefault =
        storedDefault ??
        (isActiveAssistantSection ? state.isDefaultSelected : true);
    if (isDefault) {
        return undefined;
    }
    return (
        state.selectedVersionIdBySection[ASSISTANT_SECTION_ID] ??
        (isActiveAssistantSection ? state.selectedVersionId : undefined)
    );
};

export const getAssistantDraftEdits = (
    state: AssistantDraftState,
): PromptFile[] =>
    ASSISTANT_TEMPLATE_FILENAMES.flatMap((filename) => {
        const content = state.drafts[filename];
        return content === undefined ? [] : [{ filename, content }];
    });

export const buildAssistantDraftPromptTemplates = (
    state: AssistantDraftState,
): PromptFile[] =>
    ASSISTANT_TEMPLATE_FILENAMES.map((filename) => {
        const versionContent = state.selectedVersionDetail?.prompts.find(
            (prompt) => prompt.filename === filename,
        )?.content;
        const diskContent = state.diskTemplates.find(
            (template) => template.filename === filename,
        )?.content;

        return {
            filename,
            content:
                state.drafts[filename] ?? versionContent ?? diskContent ?? "",
        };
    });
