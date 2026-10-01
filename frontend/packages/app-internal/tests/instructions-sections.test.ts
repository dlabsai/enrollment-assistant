import assert from "node:assert/strict";

import { test } from "vitest";

import {
    buildSections,
    getScopeForSectionId,
    getTemplateFilenamesForScope,
    getTemplateLabel,
} from "../src/instructions/lib/sections";

const screeningTemplate = "compliance_screening_agent_internal.j2";

test("screening instructions appear as an internal compliance prompt set", () => {
    assert.deepEqual(
        buildSections([{ filename: screeningTemplate, content: "Screen Chats." }]),
        [
            {
                id: "screening-internal",
                label: "Screening (Internal)",
                platform: "internal",
                templates: [screeningTemplate],
            },
        ],
    );
    assert.equal(getScopeForSectionId("screening-internal"), "compliance");
    assert.equal(getTemplateLabel(screeningTemplate), "Screening");
    assert.deepEqual(getTemplateFilenamesForScope("compliance", "internal"), [
        screeningTemplate,
    ]);
});
