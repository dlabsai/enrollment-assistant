import type { PromptFile, PromptSetScope } from "../types";

export type PromptPlatform = "internal" | "public";

export const INTERNAL_PROMPT_PLATFORM: PromptPlatform = "internal";

export interface AdminSection {
    id: string;
    label: string;
    platform: PromptPlatform;
    templates: string[];
}

interface SectionDefinition {
    key: string;
    label: string;
    scope: PromptSetScope;
    templates: readonly { base: string; label?: string }[];
}

const SECTION_DEFINITIONS: readonly SectionDefinition[] = [
    {
        key: "assistant",
        label: "Assistant",
        scope: "assistant",
        templates: [
            { base: "chatbot_agent", label: "Chatbot" },
            { base: "guardrails_agent", label: "Guardrails" },
        ],
    },
    {
        key: "investigation",
        label: "Investigation",
        scope: "investigation",
        templates: [{ base: "investigation_agent" }],
    },
    {
        key: "summary",
        label: "Summary",
        scope: "summary",
        templates: [{ base: "summary_agent" }],
    },
    {
        key: "title",
        label: "Title",
        scope: "title",
        templates: [{ base: "title_agent" }],
    },
    {
        key: "title-transcript",
        label: "Title Transcript",
        scope: "title_transcript",
        templates: [{ base: "title_agent_transcript" }],
    },
    {
        key: "grounding",
        label: "Grounding",
        scope: "grounding",
        templates: [{ base: "grounding_agent" }],
    },
    {
        key: "screening",
        label: "Screening",
        scope: "compliance",
        templates: [{ base: "compliance_screening_agent" }],
    },
];

const TEMPLATE_DEFINITIONS = SECTION_DEFINITIONS.flatMap((section) =>
    section.templates.map((template) => ({
        base: template.base,
        label: template.label ?? section.label,
    })),
);

const getFilenameForBase = (base: string, platform: PromptPlatform): string =>
    platform === "internal" ? `${base}_internal.j2` : `${base}.j2`;

const getBaseName = (filename: string): string =>
    filename.replace(/_internal\.j2$/u, "").replace(/\.j2$/u, "");

const formatScopeLabel = (platform: PromptPlatform): string =>
    platform === "internal" ? "Internal" : "Public";

const createSectionId = (key: string, platform: PromptPlatform): string =>
    `${key}-${platform}`;

const getDefinitionForScope = (scope: PromptSetScope): SectionDefinition => {
    const definition = SECTION_DEFINITIONS.find(
        (section) => section.scope === scope,
    );
    if (definition === undefined) {
        throw new Error(`Unknown prompt-set scope: ${scope}`);
    }
    return definition;
};

export const getPlatformForFilename = (filename: string): PromptPlatform =>
    filename.includes("_internal") ? "internal" : "public";

export const getTemplateLabel = (filename: string): string => {
    const baseName = getBaseName(filename);
    return (
        TEMPLATE_DEFINITIONS.find((template) => template.base === baseName)
            ?.label ?? baseName
    );
};

export const getScopeForSectionId = (
    sectionId?: string,
): PromptSetScope | undefined => {
    if (sectionId === undefined || sectionId === "") {
        return undefined;
    }
    const key = sectionId.replace(/-internal$/u, "").replace(/-public$/u, "");
    return SECTION_DEFINITIONS.find((section) => section.key === key)?.scope;
};

export const getSectionIdForScope = (
    scope: PromptSetScope,
    platform: PromptPlatform,
): string => createSectionId(getDefinitionForScope(scope).key, platform);

export const getPlatformForSectionId = (
    sectionId?: string,
): PromptPlatform | undefined => {
    if (sectionId === undefined || sectionId === "") {
        return undefined;
    }
    if (sectionId.endsWith("-internal")) {
        return "internal";
    }
    if (sectionId.endsWith("-public")) {
        return "public";
    }
    return undefined;
};

export const getTemplateFilenamesForScope = (
    scope: PromptSetScope,
    platform: PromptPlatform,
): string[] =>
    getDefinitionForScope(scope).templates.map((template) =>
        getFilenameForBase(template.base, platform),
    );

export const buildSections = (diskTemplates: PromptFile[]): AdminSection[] => {
    const templateSet = new Set(
        diskTemplates.map((template) => template.filename),
    );
    const sections: AdminSection[] = [];

    for (const definition of SECTION_DEFINITIONS) {
        const templates = definition.templates
            .map((template) =>
                getFilenameForBase(template.base, INTERNAL_PROMPT_PLATFORM),
            )
            .filter((filename) => templateSet.has(filename));
        if (templates.length > 0) {
            sections.push({
                id: createSectionId(
                    definition.key,
                    INTERNAL_PROMPT_PLATFORM,
                ),
                label: `${definition.label} (${formatScopeLabel(INTERNAL_PROMPT_PLATFORM)})`,
                platform: INTERNAL_PROMPT_PLATFORM,
                templates,
            });
        }
    }

    return sections;
};

export const isAssistantSectionId = (sectionId?: string): boolean =>
    sectionId?.startsWith("assistant-") ?? false;

export const getSectionIdForTemplate = (
    filename: string,
): string | undefined => {
    const baseName = getBaseName(filename);
    const definition = SECTION_DEFINITIONS.find((section) =>
        section.templates.some((template) => template.base === baseName),
    );
    return definition === undefined
        ? undefined
        : createSectionId(definition.key, getPlatformForFilename(filename));
};

export const getDefaultTemplateFilename = (
    diskTemplates: PromptFile[],
): string | undefined => {
    const templateSet = new Set(
        diskTemplates.map((template) => template.filename),
    );
    return TEMPLATE_DEFINITIONS.map((template) =>
        getFilenameForBase(template.base, INTERNAL_PROMPT_PLATFORM),
    ).find((filename) => templateSet.has(filename));
};
