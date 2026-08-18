import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    buildAssistantDraftPromptTemplates,
    getAssistantDraftEdits,
    selectAssistantDraftBaseVersionId,
    selectHasAssistantDraft,
} from "../src/instructions/lib/assistant-draft.ts";
import type { PromptSetVersion } from "../src/instructions/types/index.ts";

const baseState = {
    activeSectionId: "summary-internal",
    diskTemplates: [],
    drafts: {},
    isDefaultSelected: true,
    isDefaultSelectedBySection: {},
    selectedVersionDetail: undefined,
    selectedVersionId: undefined,
    selectedVersionIdBySection: {},
};

describe("Assistant instruction drafts", () => {
    it("selects only Assistant edits and their persisted saved base", () => {
        const state = {
            ...baseState,
            drafts: {
                "chatbot_agent_internal.j2": "Edited chatbot instructions",
                "summary_agent_internal.j2": "Edited summary instructions",
            },
            isDefaultSelectedBySection: {
                "assistant-internal": false,
            },
            selectedVersionIdBySection: {
                "assistant-internal": "saved-version-id",
            },
        };

        assert.equal(selectHasAssistantDraft(state), true);
        assert.equal(
            selectAssistantDraftBaseVersionId(state),
            "saved-version-id",
        );
        assert.deepEqual(getAssistantDraftEdits(state), [
            {
                filename: "chatbot_agent_internal.j2",
                content: "Edited chatbot instructions",
            },
        ]);
    });

    it("does not treat helper edits as an Assistant draft", () => {
        const state = {
            ...baseState,
            drafts: {
                "summary_agent_internal.j2": "Edited summary instructions",
            },
        };

        assert.equal(selectHasAssistantDraft(state), false);
        assert.deepEqual(getAssistantDraftEdits(state), []);
    });

    it("builds the complete Assistant pair from Default instructions", () => {
        const state = {
            ...baseState,
            activeSectionId: "assistant-internal",
            diskTemplates: [
                {
                    filename: "chatbot_agent_internal.j2",
                    content: "Default chatbot instructions",
                },
                {
                    filename: "guardrails_agent_internal.j2",
                    content: "Default guardrails instructions",
                },
            ],
            drafts: {
                "guardrails_agent_internal.j2": "Edited guardrails instructions",
            },
        };

        assert.deepEqual(buildAssistantDraftPromptTemplates(state), [
            {
                filename: "chatbot_agent_internal.j2",
                content: "Default chatbot instructions",
            },
            {
                filename: "guardrails_agent_internal.j2",
                content: "Edited guardrails instructions",
            },
        ]);
    });

    it("builds the complete Assistant pair from a saved version", () => {
        const selectedVersionDetail: PromptSetVersion = {
            id: "saved-version-id",
            version_number: 3,
            name: "Candidate",
            description: "Candidate instructions",
            is_internal: true,
            scope: "assistant",
            is_deployed: false,
            created_by_id: "user-id",
            created_by_name: "User",
            created_at: "2026-07-14T00:00:00Z",
            prompts: [
                {
                    id: "chatbot-prompt-id",
                    filename: "chatbot_agent_internal.j2",
                    content: "Saved chatbot instructions",
                },
                {
                    id: "guardrails-prompt-id",
                    filename: "guardrails_agent_internal.j2",
                    content: "Saved guardrails instructions",
                },
            ],
        };
        const state = {
            ...baseState,
            activeSectionId: "assistant-internal",
            drafts: {
                "chatbot_agent_internal.j2": "Edited chatbot instructions",
            },
            isDefaultSelected: false,
            selectedVersionDetail,
            selectedVersionId: "saved-version-id",
        };

        assert.deepEqual(buildAssistantDraftPromptTemplates(state), [
            {
                filename: "chatbot_agent_internal.j2",
                content: "Edited chatbot instructions",
            },
            {
                filename: "guardrails_agent_internal.j2",
                content: "Saved guardrails instructions",
            },
        ]);
    });
});
