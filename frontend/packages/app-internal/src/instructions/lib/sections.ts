import type { PromptFile, PromptSetScope } from "../types";

export type PromptPlatform = "internal" | "public";

export const INTERNAL_PROMPT_PLATFORM: PromptPlatform = "internal";

export interface AdminSection {
    id: string;
    label: string;
    platform: PromptPlatform;
    templates: string[];
}

const ASSISTANT_TEMPLATES = ["chatbot_agent", "guardrails_agent"] as const;

const ASSISTANT_TEMPLATE_SET = new Set<string>(ASSISTANT_TEMPLATES);

const HELPERS = [
    {
        key: "investigation",
        label: "Investigation",
        template: "investigation_agent",
    },
    { key: "summary", label: "Summary", template: "summary_agent" },
    { key: "title", label: "Title", template: "title_agent" },
    {
        key: "title-transcript",
        label: "Title Transcript",
        template: "title_agent_transcript",
    },
    { key: "grounding", label: "Grounding", template: "grounding_agent" },
] as const;

const SECTION_SCOPE_MAP: Record<string, PromptSetScope> = {
    assistant: "assistant",
    investigation: "investigation",
    summary: "summary",
    title: "title",
    "title-transcript": "title_transcript",
    grounding: "grounding",
};

const SCOPE_SECTION_KEY_MAP: Record<PromptSetScope, string> = {
    assistant: "assistant",
    investigation: "investigation",
    summary: "summary",
    title: "title",
    title_transcript: "title-transcript",
    grounding: "grounding",
};

const HELPER_TEMPLATE_BY_SCOPE: Record<PromptSetScope, string | undefined> = {
    assistant: undefined,
    investigation: "investigation_agent",
    summary: "summary_agent",
    title: "title_agent",
    title_transcript: "title_agent_transcript",
    grounding: "grounding_agent",
};

const TEMPLATE_LABELS: Record<string, string> = {
    chatbot_agent: "Chatbot",
    guardrails_agent: "Guardrails",
    investigation_agent: "Investigation",
    summary_agent: "Summary",
    grounding_agent: "Grounding",
    title_agent: "Title",
    title_agent_transcript: "Title Transcript",
};

const DEFAULT_TEMPLATE_PRIORITY = [
    "chatbot_agent_internal.j2",
    "guardrails_agent_internal.j2",
    "investigation_agent_internal.j2",
    "summary_agent_internal.j2",
    "title_agent_internal.j2",
    "title_agent_transcript_internal.j2",
    "grounding_agent_internal.j2",
];

const getFilenameForBase = (base: string, platform: PromptPlatform): string =>
    platform === "internal" ? `${base}_internal.j2` : `${base}.j2`;

export const getPlatformForFilename = (filename: string): PromptPlatform =>
    filename.includes("_internal") ? "internal" : "public";

export const getTemplateLabel = (filename: string): string => {
    const baseName = filename
        .replace(/_internal\.j2$/u, "")
        .replace(/\.j2$/u, "");
    return TEMPLATE_LABELS[baseName] ?? baseName;
};

const formatScopeLabel = (platform: PromptPlatform): string =>
    platform === "internal" ? "Internal" : "Public";

const createSectionId = (key: string, platform: PromptPlatform): string =>
    `${key}-${platform}`;

export const getScopeForSectionId = (
    sectionId?: string,
): PromptSetScope | undefined => {
    if (sectionId === undefined || sectionId === "") {
        return undefined;
    }
    const key = sectionId.replace(/-internal$/u, "").replace(/-public$/u, "");
    return SECTION_SCOPE_MAP[key];
};

export const getSectionIdForScope = (
    scope: PromptSetScope,
    platform: PromptPlatform,
): string => createSectionId(SCOPE_SECTION_KEY_MAP[scope], platform);

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
): string[] => {
    if (scope === "assistant") {
        return ASSISTANT_TEMPLATES.map((base) =>
            getFilenameForBase(base, platform),
        );
    }

    const helperTemplate = HELPER_TEMPLATE_BY_SCOPE[scope];
    if (helperTemplate === undefined) {
        return [];
    }
    return [getFilenameForBase(helperTemplate, platform)];
};

export const buildSections = (diskTemplates: PromptFile[]): AdminSection[] => {
    const templateSet = new Set(
        diskTemplates.map((template) => template.filename),
    );
    const sections: AdminSection[] = [];

    const addAssistantSection = (platform: PromptPlatform): void => {
        const templates = ASSISTANT_TEMPLATES.map((base) =>
            getFilenameForBase(base, platform),
        ).filter((filename) => templateSet.has(filename));

        if (templates.length === 0) {
            return;
        }

        sections.push({
            id: createSectionId("assistant", platform),
            label: `Assistant (${formatScopeLabel(platform)})`,
            platform,
            templates,
        });
    };

    const addHelperSections = (platform: PromptPlatform): void => {
        for (const helper of HELPERS) {
            const filename = getFilenameForBase(helper.template, platform);
            if (templateSet.has(filename)) {
                sections.push({
                    id: createSectionId(helper.key, platform),
                    label: `${helper.label} (${formatScopeLabel(platform)})`,
                    platform,
                    templates: [filename],
                });
            }
        }
    };

    addAssistantSection(INTERNAL_PROMPT_PLATFORM);
    addHelperSections(INTERNAL_PROMPT_PLATFORM);

    return sections;
};

export const isAssistantSectionId = (sectionId?: string): boolean =>
    sectionId?.startsWith("assistant-") ?? false;

export const getSectionIdForTemplate = (
    filename: string,
): string | undefined => {
    const platform = getPlatformForFilename(filename);
    const baseName = filename
        .replace(/_internal\.j2$/u, "")
        .replace(/\.j2$/u, "");

    if (ASSISTANT_TEMPLATE_SET.has(baseName)) {
        return createSectionId("assistant", platform);
    }

    const helper = HELPERS.find((item) => item.template === baseName);
    if (helper) {
        return createSectionId(helper.key, platform);
    }

    return undefined;
};

export const getDefaultTemplateFilename = (
    diskTemplates: PromptFile[],
): string | undefined => {
    const templateSet = new Set(
        diskTemplates.map((template) => template.filename),
    );

    return DEFAULT_TEMPLATE_PRIORITY.find((filename) =>
        templateSet.has(filename),
    );
};
