import { isApiError } from "@va/shared/lib/api-client";
import { toast } from "sonner";
import { createStore } from "zustand";
import { persist, subscribeWithSelector } from "zustand/middleware";
import type { Mutate, StateCreator, StoreApi } from "zustand/vanilla";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type {
    ActiveVersion,
    ConfirmDialogAction,
    InstructionsTab,
    PromptFile,
    PromptSetVersion,
    PromptSetVersionCreate,
    PromptSetVersionListItem,
} from "../types";
import {
    createVersion as apiCreateVersion,
    deleteVersion as apiDeleteVersion,
    deployVersion as apiDeployVersion,
    fetchDeployedVersion,
    fetchDiskTemplates,
    fetchVersionDetail,
    fetchVersions,
    undeployVersion as apiUndeployVersion,
} from "./prompt-management-api";
import {
    getDefaultTemplateFilename,
    getPlatformForFilename,
    getPlatformForSectionId,
    getScopeForSectionId,
    getSectionIdForScope,
    getSectionIdForTemplate,
    getTemplateFilenamesForScope,
    type PromptPlatform,
} from "./sections";

const STORAGE_KEY = "instructions-store";

interface InstructionsState {
    diskTemplates: PromptFile[];
    diskTemplatesLoaded: boolean;
    versionsBySection: Record<string, PromptSetVersionListItem[]>;
    versionsLoadedBySection: Record<string, boolean>;
    deployedVersion?: ActiveVersion;
    selectedVersionDetail?: PromptSetVersion;
    activePlatform: PromptPlatform;

    activeSectionId?: string;
    expandedSections: Record<string, boolean>;
    selectedVersionIdBySection: Record<string, string | undefined>;
    isDefaultSelectedBySection: Record<string, boolean | undefined>;

    activeTab: InstructionsTab;
    showGuide: boolean;
    hasSeenGuide: boolean;
    error?: string;

    selectedTemplate?: string;
    editedContent: string;
    drafts: Record<string, string>;
    showDiff: boolean;
    wrapLines: boolean;
    editorKey: number;

    selectedVersionId?: string;
    isDefaultSelected: boolean;

    versionName: string;
    versionDescription: string;

    confirmDialogAction?: ConfirmDialogAction;
    confirmDialogVersionId?: string;

    testChatVersionId: string;
    testChatChatId?: string;
    testChatParentMessageId?: string;

    isChatPanelOpen: boolean;

    isCreating: boolean;
    isDeploying: boolean;
    isDeleting: boolean;
}

export interface InstructionsActions {
    loadDiskTemplates: () => Promise<void>;
    loadVersions: (sectionId?: string) => Promise<void>;
    loadDeployedVersion: (sectionId?: string) => Promise<void>;
    loadVersionDetail: (versionId: string) => Promise<void>;

    setActiveTab: (tab: InstructionsTab) => void;
    setActivePlatform: (platform: PromptPlatform) => void;
    setActiveSection: (sectionId: string, platform: PromptPlatform) => void;
    setSectionExpanded: (sectionId: string, expanded: boolean) => void;
    dismissGuide: () => void;
    showGuidePanel: () => void;
    setError: (error?: string) => void;
    clearError: () => void;

    selectTemplate: (filename: string) => void;

    selectVersion: (versionId: string) => void;
    selectDefault: () => void;
    requestSelectVersion: (versionId: string) => void;
    requestSelectDefault: () => void;

    updateContent: (content: string) => void;
    toggleDiff: () => void;
    toggleWrapLines: () => void;
    requestResetTemplate: () => void;
    resetTemplate: () => void;

    setVersionName: (name: string) => void;
    setVersionDescription: (description: string) => void;

    createVersion: () => Promise<void>;
    deployVersion: (versionId: string) => Promise<void>;
    undeployVersion: () => Promise<void>;
    requestDeleteVersion: (versionId: string) => void;
    deleteVersion: () => Promise<void>;

    closeConfirmDialog: () => void;
    confirmAction: () => Promise<void>;

    setTestChatVersion: (versionId: string) => void;
    setTestChatChat: (chatId: string, parentMessageId?: string) => void;
    clearTestChat: () => void;
    setChatPanelOpen: (open: boolean) => void;
    toggleChatPanel: () => void;

    getBaseContent: (filename: string) => string;
}

const withErrorHandling = async <T>(
    operation: () => Promise<T>,
    fallbackMessage: string,
    onError: (message: string) => void,
): Promise<T | undefined> => {
    try {
        return await operation();
    } catch (error) {
        onError(error instanceof Error ? error.message : fallbackMessage);
        return undefined;
    }
};

const findTemplateContent = (
    filename: string,
    versionDetail: PromptSetVersion | undefined,
    diskTemplates: PromptFile[],
): string => {
    if (versionDetail) {
        const versionPrompt = versionDetail.prompts.find(
            (prompt) => prompt.filename === filename,
        );
        if (versionPrompt) {
            return versionPrompt.content;
        }
    }
    const diskTemplate = diskTemplates.find(
        (template) => template.filename === filename,
    );
    return diskTemplate?.content ?? "";
};

export const selectHasUnsavedChanges = (state: InstructionsState): boolean =>
    Object.keys(state.drafts).length > 0;

const selectHasUnsavedChangesInSection = (
    state: InstructionsState,
    sectionId: string | undefined,
): boolean => {
    if (sectionId === undefined) {
        return selectHasUnsavedChanges(state);
    }

    return Object.keys(state.drafts).some(
        (filename) => getSectionIdForTemplate(filename) === sectionId,
    );
};

export const selectIsLiveDefault = (state: InstructionsState): boolean =>
    state.deployedVersion !== undefined &&
    state.deployedVersion.id === undefined;

export type InstructionsStoreState = InstructionsState & InstructionsActions;

type PersistedInstructionsState = Pick<
    InstructionsStoreState,
    | "hasSeenGuide"
    | "activePlatform"
    | "activeSectionId"
    | "expandedSections"
    | "selectedVersionId"
    | "selectedVersionIdBySection"
    | "isDefaultSelected"
    | "isDefaultSelectedBySection"
    | "selectedTemplate"
    | "drafts"
    | "wrapLines"
    | "isChatPanelOpen"
>;

type InstructionsStoreMutators = [
    ["zustand/subscribeWithSelector", never],
    ["zustand/persist", PersistedInstructionsState],
];

export type InstructionsStore = Mutate<
    StoreApi<InstructionsStoreState>,
    InstructionsStoreMutators
>;

type InstructionsSetState = Parameters<StateCreator<InstructionsStoreState>>[0];
type InstructionsGetState = Parameters<StateCreator<InstructionsStoreState>>[1];

const isPersistedInstructionsState = (
    value: unknown,
): value is PersistedInstructionsState => {
    if (value === null || typeof value !== "object") {
        return false;
    }
    const hasSeenGuide: unknown = Reflect.get(value, "hasSeenGuide");
    return typeof hasSeenGuide === "boolean";
};

const filterInternalSectionEntries = <T>(
    entries: Record<string, T>,
): Record<string, T> =>
    Object.fromEntries(
        Object.entries(entries).filter(
            ([sectionId]) => getPlatformForSectionId(sectionId) === "internal",
        ),
    ) as Record<string, T>;

const filterInternalTemplateEntries = <T>(
    entries: Record<string, T>,
): Record<string, T> =>
    Object.fromEntries(
        Object.entries(entries).filter(
            ([filename]) =>
                getPlatformForFilename(filename) === "internal" &&
                getSectionIdForTemplate(filename) !== undefined,
        ),
    ) as Record<string, T>;

const getDefaultTemplateForSection = (
    diskTemplates: PromptFile[],
    sectionId: string | undefined,
): string | undefined => {
    const scope = getScopeForSectionId(sectionId);
    const platform = getPlatformForSectionId(sectionId);
    if (scope === undefined || platform === undefined) {
        return undefined;
    }

    const templateSet = new Set(
        diskTemplates.map((template) => template.filename),
    );
    return getTemplateFilenamesForScope(scope, platform).find((filename) =>
        templateSet.has(filename),
    );
};

const createInitialInstructionsState = (): InstructionsState => ({
    diskTemplates: [],
    diskTemplatesLoaded: false,
    versionsBySection: {},
    versionsLoadedBySection: {},
    deployedVersion: undefined,
    selectedVersionDetail: undefined,
    activePlatform: "internal",
    activeSectionId: undefined,
    expandedSections: {},
    selectedVersionIdBySection: {},
    isDefaultSelectedBySection: {},
    activeTab: "editor",
    showGuide: true,
    hasSeenGuide: false,
    error: undefined,
    selectedTemplate: undefined,
    editedContent: "",
    drafts: {},
    showDiff: false,
    wrapLines: true,
    editorKey: 0,
    selectedVersionId: undefined,
    isDefaultSelected: false,
    versionName: "",
    versionDescription: "",
    confirmDialogAction: undefined,
    confirmDialogVersionId: undefined,
    testChatVersionId: "",
    testChatChatId: undefined,
    testChatParentMessageId: undefined,
    isChatPanelOpen: true,
    isCreating: false,
    isDeploying: false,
    isDeleting: false,
});

const createInstructionsActions = (
    api: AuthenticatedApi,
    set: InstructionsSetState,
    get: InstructionsGetState,
): InstructionsActions => ({
    loadDiskTemplates: async (): Promise<void> => {
        const templates = await withErrorHandling(
            async () => fetchDiskTemplates(api),
            "Failed to load templates",
            (error) => {
                set({ error });
            },
        );

        if (templates !== undefined) {
            set({
                diskTemplates: templates,
                diskTemplatesLoaded: true,
            });
            const { selectedTemplate, editedContent, activeSectionId } = get();
            if (selectedTemplate !== undefined && editedContent === "") {
                get().selectTemplate(selectedTemplate);
            }
            if (selectedTemplate === undefined) {
                const defaultTemplate =
                    getDefaultTemplateForSection(templates, activeSectionId) ??
                    getDefaultTemplateFilename(templates);
                if (defaultTemplate !== undefined) {
                    get().selectTemplate(defaultTemplate);
                }
            }
        }
    },

    loadVersions: async (sectionId?: string): Promise<void> => {
        const targetSectionId = sectionId ?? get().activeSectionId;
        const scope = getScopeForSectionId(targetSectionId);
        const platform = getPlatformForSectionId(targetSectionId);
        if (
            targetSectionId === undefined ||
            targetSectionId === "" ||
            scope === undefined ||
            platform === undefined
        ) {
            return;
        }

        const versions = await withErrorHandling(
            async () => fetchVersions(api, platform === "internal", scope),

            "Failed to load versions",
            (error) => {
                set({ error });
            },
        );

        if (versions) {
            const normalized = versions.map((version) => ({
                ...version,
                description: version.description ?? undefined,
            }));
            const storedVersionId =
                get().selectedVersionIdBySection[targetSectionId];
            const hasStoredVersion =
                storedVersionId !== undefined && storedVersionId !== "";
            const hasStoredSelection =
                hasStoredVersion &&
                normalized.some((version) => version.id === storedVersionId);
            const { activeSectionId } = get();
            const shouldResetSelection =
                hasStoredVersion && !hasStoredSelection;

            set({
                versionsBySection: {
                    ...get().versionsBySection,
                    [targetSectionId]: normalized,
                },
                versionsLoadedBySection: {
                    ...get().versionsLoadedBySection,
                    [targetSectionId]: true,
                },
                selectedVersionIdBySection: shouldResetSelection
                    ? {
                          ...get().selectedVersionIdBySection,
                          [targetSectionId]: undefined,
                      }
                    : get().selectedVersionIdBySection,
                isDefaultSelectedBySection: shouldResetSelection
                    ? {
                          ...get().isDefaultSelectedBySection,
                          [targetSectionId]: true,
                      }
                    : get().isDefaultSelectedBySection,
                selectedVersionId:
                    shouldResetSelection &&
                    activeSectionId === targetSectionId &&
                    get().selectedVersionId === storedVersionId
                        ? undefined
                        : get().selectedVersionId,
                selectedVersionDetail:
                    shouldResetSelection &&
                    activeSectionId === targetSectionId &&
                    get().selectedVersionId === storedVersionId
                        ? undefined
                        : get().selectedVersionDetail,
                isDefaultSelected:
                    shouldResetSelection && activeSectionId === targetSectionId
                        ? true
                        : get().isDefaultSelected,
                error:
                    shouldResetSelection && activeSectionId === targetSectionId
                        ? "Selected version is no longer available. It may have been deleted."
                        : get().error,
            });
        }
    },

    loadDeployedVersion: async (sectionId?: string): Promise<void> => {
        const targetSectionId = sectionId ?? get().activeSectionId;
        const scope = getScopeForSectionId(targetSectionId);
        const platform = getPlatformForSectionId(targetSectionId);
        if (
            targetSectionId === undefined ||
            targetSectionId === "" ||
            scope === undefined ||
            platform === undefined
        ) {
            set({ deployedVersion: undefined });
            return;
        }

        const deployed = await withErrorHandling(
            async () =>
                fetchDeployedVersion(api, platform === "internal", scope),

            "Failed to load deployed version",
            (error) => {
                set({ error });
            },
        );

        if (deployed) {
            set({
                deployedVersion: {
                    ...deployed,
                    id: deployed.id ?? undefined,
                    version_number: deployed.version_number ?? undefined,
                    name: deployed.name ?? undefined,
                },
            });
        }
    },

    loadVersionDetail: async (versionId: string): Promise<void> => {
        try {
            const detail = await fetchVersionDetail(api, versionId);
            const { selectedTemplate, drafts, diskTemplates, editedContent } =
                get();
            const hasDraft =
                selectedTemplate !== undefined && selectedTemplate in drafts;
            const nextEditedContent =
                selectedTemplate !== undefined && !hasDraft
                    ? findTemplateContent(
                          selectedTemplate,
                          detail,
                          diskTemplates,
                      )
                    : editedContent;

            set({
                selectedVersionDetail: {
                    ...detail,
                    description: detail.description ?? undefined,
                },
                editedContent: nextEditedContent,
            });
        } catch (error) {
            const { activeSectionId } = get();
            const message =
                isApiError(error) && error.status === 404
                    ? "Selected version is no longer available. It may have been deleted."
                    : error instanceof Error
                      ? error.message
                      : "Failed to load version detail";
            set({
                error: message,
                selectedVersionId: undefined,
                selectedVersionDetail: undefined,
                isDefaultSelected: true,
                selectedVersionIdBySection:
                    activeSectionId === undefined
                        ? get().selectedVersionIdBySection
                        : {
                              ...get().selectedVersionIdBySection,
                              [activeSectionId]: undefined,
                          },
                isDefaultSelectedBySection:
                    activeSectionId === undefined
                        ? get().isDefaultSelectedBySection
                        : {
                              ...get().isDefaultSelectedBySection,
                              [activeSectionId]: true,
                          },
            });
        }
    },

    setActiveTab: (tab: InstructionsTab): void => {
        set({ activeTab: tab });
        if (tab === "test-chat") {
            const sectionId = getSectionIdForScope(
                "assistant",
                get().activePlatform,
            );
            void get().loadVersions(sectionId);
        }
    },

    setActivePlatform: (platform: PromptPlatform): void => {
        const { activePlatform } = get();
        if (activePlatform === platform) {
            return;
        }
        set({
            activePlatform: platform,
            deployedVersion: undefined,
            selectedVersionId: undefined,
            selectedVersionDetail: undefined,
            isDefaultSelected: true,
            selectedTemplate: undefined,
            editedContent: "",
            showDiff: false,
            editorKey: get().editorKey + 1,
            testChatVersionId: "",
            testChatChatId: undefined,
            testChatParentMessageId: undefined,
        });
    },

    setActiveSection: (sectionId: string, platform: PromptPlatform): void => {
        const state = get();
        if (state.activePlatform !== platform) {
            state.setActivePlatform(platform);
        }
        const storedVersionId = state.selectedVersionIdBySection[sectionId];
        const storedDefault =
            state.isDefaultSelectedBySection[sectionId] ?? true;
        const versionsLoaded = state.versionsLoadedBySection[sectionId];

        set({
            activeSectionId: sectionId,
            selectedTemplate: undefined,
            selectedVersionId: storedDefault ? undefined : storedVersionId,
            isDefaultSelected: storedDefault,
            selectedVersionDetail: undefined,
            isDefaultSelectedBySection:
                state.isDefaultSelectedBySection[sectionId] === undefined
                    ? {
                          ...state.isDefaultSelectedBySection,
                          [sectionId]: true,
                      }
                    : state.isDefaultSelectedBySection,
        });

        if (!versionsLoaded) {
            void state.loadVersions(sectionId);
        }
        void state.loadDeployedVersion(sectionId);

        if (
            storedVersionId !== undefined &&
            storedVersionId !== "" &&
            !storedDefault
        ) {
            void state.loadVersionDetail(storedVersionId);
        }
    },

    setSectionExpanded: (sectionId: string, expanded: boolean): void => {
        set({
            expandedSections: {
                ...get().expandedSections,
                [sectionId]: expanded,
            },
        });
    },

    dismissGuide: (): void => {
        set({ showGuide: false, hasSeenGuide: true });
    },

    showGuidePanel: (): void => {
        set({ showGuide: true, hasSeenGuide: true });
    },

    setError: (error?: string): void => {
        set({ error });
    },

    clearError: (): void => {
        set({ error: undefined });
    },

    selectTemplate: (filename: string): void => {
        const {
            drafts,
            selectedVersionDetail,
            diskTemplates,
            activePlatform,
            activeSectionId,
            selectedVersionId,
            isDefaultSelected,
            selectedVersionIdBySection,
            isDefaultSelectedBySection,
        } = get();
        const platform = getPlatformForFilename(filename);
        const platformChanged = platform !== activePlatform;
        if (platformChanged) {
            get().setActivePlatform(platform);
        }

        const sectionId = getSectionIdForTemplate(filename);
        const sectionChanged =
            sectionId !== undefined && sectionId !== activeSectionId;
        const storedVersionId =
            sectionId === undefined
                ? undefined
                : selectedVersionIdBySection[sectionId];
        const storedDefault =
            sectionId === undefined
                ? undefined
                : (isDefaultSelectedBySection[sectionId] ?? true);
        const effectiveVersionDetail =
            platformChanged || sectionChanged
                ? undefined
                : selectedVersionDetail;

        const content =
            drafts[filename] ??
            findTemplateContent(
                filename,
                effectiveVersionDetail,
                diskTemplates,
            );
        const nextIsDefaultSelectedBySection =
            sectionId !== undefined &&
            isDefaultSelectedBySection[sectionId] === undefined
                ? {
                      ...isDefaultSelectedBySection,
                      [sectionId]: true,
                  }
                : isDefaultSelectedBySection;
        const resolvedStoredDefault = storedDefault ?? true;
        const nextSelectedVersionId = sectionChanged
            ? resolvedStoredDefault
                ? undefined
                : storedVersionId
            : selectedVersionId;
        const nextIsDefaultSelected = sectionChanged
            ? resolvedStoredDefault
            : isDefaultSelected;

        set({
            selectedTemplate: filename,
            editedContent: content,
            editorKey: get().editorKey + 1,
            showDiff: filename in drafts,
            activeSectionId: sectionId ?? get().activeSectionId,
            selectedVersionId: nextSelectedVersionId,
            isDefaultSelected: nextIsDefaultSelected,
            selectedVersionDetail: sectionChanged
                ? undefined
                : selectedVersionDetail,
            expandedSections:
                sectionId === undefined
                    ? get().expandedSections
                    : {
                          ...get().expandedSections,
                          [sectionId]: true,
                      },
            isDefaultSelectedBySection: nextIsDefaultSelectedBySection,
        });

        if (
            sectionChanged &&
            storedVersionId !== undefined &&
            storedVersionId !== "" &&
            storedDefault === false
        ) {
            void get().loadVersionDetail(storedVersionId);
        }
    },

    selectVersion: (versionId: string): void => {
        const { activePlatform, activeSectionId, drafts } = get();
        const sectionId =
            activeSectionId ??
            getSectionIdForScope("assistant", activePlatform);
        const versions = sectionId
            ? get().versionsBySection[sectionId]
            : undefined;
        const version = versions?.find(
            (candidate) => candidate.id === versionId,
        );
        if (version) {
            get().setActivePlatform(
                version.is_internal ? "internal" : "public",
            );
        }
        const remainingDrafts = Object.fromEntries(
            Object.entries(drafts).filter(
                ([filename]) => getSectionIdForTemplate(filename) !== sectionId,
            ),
        );
        set({
            selectedVersionId: versionId,
            isDefaultSelected: false,
            selectedTemplate: undefined,
            drafts: remainingDrafts,
            editedContent: "",
            selectedVersionDetail: undefined,
            selectedVersionIdBySection:
                activeSectionId === undefined
                    ? get().selectedVersionIdBySection
                    : {
                          ...get().selectedVersionIdBySection,
                          [activeSectionId]: versionId,
                      },
            isDefaultSelectedBySection:
                activeSectionId === undefined
                    ? get().isDefaultSelectedBySection
                    : {
                          ...get().isDefaultSelectedBySection,
                          [activeSectionId]: false,
                      },
        });
        void get().loadVersionDetail(versionId);
    },

    selectDefault: (): void => {
        const { activePlatform, activeSectionId, drafts } = get();
        const sectionId =
            activeSectionId ??
            getSectionIdForScope("assistant", activePlatform);
        const remainingDrafts = Object.fromEntries(
            Object.entries(drafts).filter(
                ([filename]) => getSectionIdForTemplate(filename) !== sectionId,
            ),
        );
        set({
            selectedVersionId: undefined,
            isDefaultSelected: true,
            selectedTemplate: undefined,
            drafts: remainingDrafts,
            editedContent: "",
            selectedVersionDetail: undefined,
            editorKey: get().editorKey + 1,
            selectedVersionIdBySection:
                activeSectionId === undefined
                    ? get().selectedVersionIdBySection
                    : {
                          ...get().selectedVersionIdBySection,
                          [activeSectionId]: undefined,
                      },
            isDefaultSelectedBySection:
                activeSectionId === undefined
                    ? get().isDefaultSelectedBySection
                    : {
                          ...get().isDefaultSelectedBySection,
                          [activeSectionId]: true,
                      },
        });
    },

    requestSelectVersion: (versionId: string): void => {
        const { selectedVersionId, activePlatform, activeSectionId } = get();
        if (versionId === selectedVersionId) {
            return;
        }
        const sectionId =
            activeSectionId ??
            getSectionIdForScope("assistant", activePlatform);

        if (selectHasUnsavedChangesInSection(get(), sectionId)) {
            set({
                confirmDialogAction: "switch-version",
                confirmDialogVersionId: versionId,
            });
        } else {
            get().selectVersion(versionId);
        }
    },

    requestSelectDefault: (): void => {
        const { activePlatform, activeSectionId } = get();
        const sectionId =
            activeSectionId ??
            getSectionIdForScope("assistant", activePlatform);
        if (selectHasUnsavedChangesInSection(get(), sectionId)) {
            set({
                confirmDialogAction: "select-default",
                confirmDialogVersionId: undefined,
            });
        } else {
            get().selectDefault();
        }
    },

    updateContent: (content: string): void => {
        const { selectedTemplate, drafts } = get();
        if (selectedTemplate === undefined) {
            return;
        }

        const baseContent = get().getBaseContent(selectedTemplate);
        if (content === baseContent) {
            const { [selectedTemplate]: removed, ...restDrafts } = drafts;
            void removed;
            set({
                editedContent: content,
                drafts: restDrafts,
            });
            return;
        }

        set({
            editedContent: content,
            drafts: { ...drafts, [selectedTemplate]: content },
        });
    },

    toggleDiff: (): void => {
        set({ showDiff: !get().showDiff });
    },
    toggleWrapLines: (): void => {
        set({ wrapLines: !get().wrapLines });
    },

    requestResetTemplate: (): void => {
        set({ confirmDialogAction: "reset-template" });
    },

    resetTemplate: (): void => {
        const { selectedTemplate, drafts } = get();
        if (selectedTemplate === undefined) {
            return;
        }

        const baseContent = get().getBaseContent(selectedTemplate);
        const { [selectedTemplate]: removed, ...restDrafts } = drafts;
        void removed;

        set({
            editedContent: baseContent,
            drafts: restDrafts,
            showDiff: false,
            editorKey: get().editorKey + 1,
        });
    },

    setVersionName: (name: string): void => {
        set({ versionName: name });
    },

    setVersionDescription: (description: string): void => {
        set({ versionDescription: description });
    },

    createVersion: async (): Promise<void> => {
        const {
            versionName,
            versionDescription,
            drafts,
            diskTemplates,
            activePlatform,
            activeSectionId,
        } = get();

        if (!versionName.trim()) {
            set({ error: "Please enter a version name" });
            return;
        }

        if (Object.keys(drafts).length === 0) {
            set({
                error: "No instructions have been modified",
            });
            return;
        }

        const draftSections = new Set(
            Object.keys(drafts)
                .map((filename) => getSectionIdForTemplate(filename))
                .filter(
                    (sectionId): sectionId is string => sectionId !== undefined,
                ),
        );

        const sectionId =
            activeSectionId ??
            (draftSections.size === 1 ? [...draftSections][0] : undefined);
        const scope = getScopeForSectionId(sectionId);
        const platform = getPlatformForSectionId(sectionId) ?? activePlatform;

        if (
            sectionId === undefined ||
            sectionId === "" ||
            scope === undefined
        ) {
            set({
                error: "Select a section before saving a version.",
            });
            return;
        }

        const scopeFilenames = getTemplateFilenamesForScope(scope, platform);
        const scopeDrafts = Object.keys(drafts).filter((filename) =>
            scopeFilenames.includes(filename),
        );
        if (scopeDrafts.length === 0) {
            set({
                error: "No instructions have been modified in this section.",
            });
            return;
        }

        if (platform !== activePlatform) {
            get().setActivePlatform(platform);
        }

        const templateMap = new Map(
            diskTemplates.map((template) => [template.filename, template]),
        );
        const scopeTemplates = scopeFilenames
            .map((filename) => templateMap.get(filename))
            .filter(
                (template): template is PromptFile => template !== undefined,
            );

        if (scopeTemplates.length === 0) {
            set({
                error: "No templates found for this section.",
            });
            return;
        }

        if (scopeTemplates.length !== scopeFilenames.length) {
            set({
                error: "Some templates are missing for this section.",
            });
            return;
        }

        set({ isCreating: true, error: undefined });

        const data: PromptSetVersionCreate = {
            name: versionName,
            ...(versionDescription ? { description: versionDescription } : {}),
            is_internal: platform === "internal",
            scope,
            prompts: scopeTemplates.map((template) => ({
                filename: template.filename,
                content: drafts[template.filename] ?? template.content,
            })),
        };

        const result = await withErrorHandling(
            async () => apiCreateVersion(api, data),
            "Failed to create version",
            (error) => {
                set({ error });
            },
        );

        if (result) {
            set({
                versionName: "",
                versionDescription: "",
                drafts: {},
                editedContent: "",
                selectedTemplate: undefined,
            });
            await get().loadVersions(sectionId);
            toast.success("Version created");
        }

        set({ isCreating: false });
    },

    deployVersion: async (versionId: string): Promise<void> => {
        const sectionId = get().activeSectionId;
        set({ isDeploying: true, error: undefined });

        const result = await withErrorHandling(
            async () => apiDeployVersion(api, versionId),
            "Failed to deploy version",
            (error) => {
                set({ error });
            },
        );

        if (result) {
            await Promise.all([
                get().loadVersions(sectionId),
                get().loadDeployedVersion(sectionId),
            ]);
            toast.success("Version deployed");
        }

        set({ isDeploying: false });
    },

    undeployVersion: async (): Promise<void> => {
        const { activeSectionId, activePlatform } = get();
        const sectionId =
            activeSectionId ??
            getSectionIdForScope("assistant", activePlatform);
        const scope = getScopeForSectionId(sectionId);
        const platform = getPlatformForSectionId(sectionId) ?? activePlatform;
        if (scope === undefined) {
            set({ error: "Select a section before undeploying." });
            return;
        }

        set({ isDeploying: true, error: undefined });

        const result = await withErrorHandling(
            async () => apiUndeployVersion(api, platform === "internal", scope),
            "Failed to undeploy version",
            (error) => {
                set({ error });
            },
        );

        if (result) {
            await Promise.all([
                get().loadVersions(sectionId),
                get().loadDeployedVersion(sectionId),
            ]);
            toast.success("Default instructions restored");
        }

        set({ isDeploying: false });
    },

    requestDeleteVersion: (versionId: string): void => {
        set({
            confirmDialogAction: "delete-version",
            confirmDialogVersionId: versionId,
        });
    },

    deleteVersion: async (): Promise<void> => {
        const {
            confirmDialogVersionId,
            selectedVersionId,
            selectedVersionIdBySection,
            isDefaultSelectedBySection,
            testChatVersionId,
        } = get();
        if (confirmDialogVersionId === undefined) {
            return;
        }

        set({ isDeleting: true, error: undefined });

        const success = await withErrorHandling(
            async () => {
                await apiDeleteVersion(api, confirmDialogVersionId);
                return true;
            },
            "Failed to delete version",
            (error) => {
                set({ error });
            },
        );

        if (success === true) {
            const nextSelectedVersionBySection = {
                ...selectedVersionIdBySection,
            };
            const nextDefaultSelectedBySection = {
                ...isDefaultSelectedBySection,
            };

            for (const [sectionId, versionId] of Object.entries(
                selectedVersionIdBySection,
            )) {
                if (versionId === confirmDialogVersionId) {
                    nextSelectedVersionBySection[sectionId] = undefined;
                    nextDefaultSelectedBySection[sectionId] = true;
                }
            }

            set({
                selectedVersionId:
                    selectedVersionId === confirmDialogVersionId
                        ? undefined
                        : selectedVersionId,
                selectedVersionDetail:
                    selectedVersionId === confirmDialogVersionId
                        ? undefined
                        : get().selectedVersionDetail,
                selectedVersionIdBySection: nextSelectedVersionBySection,
                isDefaultSelectedBySection: nextDefaultSelectedBySection,
                isDefaultSelected:
                    selectedVersionId === confirmDialogVersionId
                        ? true
                        : get().isDefaultSelected,
                testChatVersionId:
                    testChatVersionId === confirmDialogVersionId
                        ? ""
                        : testChatVersionId,
                testChatChatId:
                    testChatVersionId === confirmDialogVersionId
                        ? undefined
                        : get().testChatChatId,
                testChatParentMessageId:
                    testChatVersionId === confirmDialogVersionId
                        ? undefined
                        : get().testChatParentMessageId,
            });

            await get().loadVersions(get().activeSectionId);
            toast.success("Version deleted");
        }

        set({ isDeleting: false, confirmDialogAction: undefined });
    },

    closeConfirmDialog: (): void => {
        set({
            confirmDialogAction: undefined,
            confirmDialogVersionId: undefined,
        });
    },

    confirmAction: async (): Promise<void> => {
        const {
            confirmDialogAction,
            confirmDialogVersionId,
            selectVersion,
            selectDefault,
            resetTemplate,
            deleteVersion,
        } = get();

        let discardedDrafts = false;

        switch (confirmDialogAction) {
            case undefined: {
                break;
            }
            case "switch-version": {
                if (
                    confirmDialogVersionId !== undefined &&
                    confirmDialogVersionId !== ""
                ) {
                    selectVersion(confirmDialogVersionId);
                    discardedDrafts = true;
                }
                break;
            }
            case "select-default": {
                selectDefault();
                discardedDrafts = true;
                break;
            }
            case "reset-template": {
                resetTemplate();
                break;
            }
            case "delete-version": {
                await deleteVersion();
                return;
            }
            default: {
                break;
            }
        }

        set({
            confirmDialogAction: undefined,
            confirmDialogVersionId: undefined,
        });

        if (discardedDrafts) {
            toast.success("Drafts discarded");
        }
    },

    setTestChatVersion: (versionId: string): void => {
        set({
            testChatVersionId: versionId,
            testChatChatId: undefined,
            testChatParentMessageId: undefined,
        });
    },

    setTestChatChat: (chatId: string, parentMessageId?: string): void => {
        set({
            testChatChatId: chatId,
            testChatParentMessageId: parentMessageId,
        });
    },

    clearTestChat: (): void => {
        set({
            testChatChatId: undefined,
            testChatParentMessageId: undefined,
        });
    },

    setChatPanelOpen: (open: boolean): void => {
        set({ isChatPanelOpen: open });
    },

    toggleChatPanel: (): void => {
        set({ isChatPanelOpen: !get().isChatPanelOpen });
    },

    getBaseContent: (filename: string): string => {
        const { selectedVersionDetail, diskTemplates } = get();
        return findTemplateContent(
            filename,
            selectedVersionDetail,
            diskTemplates,
        );
    },
});

export const createInstructionsStore = (
    api: AuthenticatedApi,
): InstructionsStore =>
    createStore<InstructionsStoreState>()(
        subscribeWithSelector(
            persist(
                (set, get) => ({
                    ...createInitialInstructionsState(),
                    // eslint-disable-next-line @typescript-eslint/strict-void-return
                    ...createInstructionsActions(api, set, get),
                }),
                {
                    name: STORAGE_KEY,
                    partialize: (
                        state: InstructionsStoreState,
                    ): PersistedInstructionsState => ({
                        hasSeenGuide: state.hasSeenGuide,
                        activePlatform: state.activePlatform,
                        activeSectionId: state.activeSectionId,
                        expandedSections: state.expandedSections,
                        selectedTemplate: state.selectedTemplate,
                        selectedVersionId: state.selectedVersionId,
                        selectedVersionIdBySection:
                            state.selectedVersionIdBySection,
                        isDefaultSelected: state.isDefaultSelected,
                        isDefaultSelectedBySection:
                            state.isDefaultSelectedBySection,
                        drafts: state.drafts,
                        wrapLines: state.wrapLines,
                        isChatPanelOpen: state.isChatPanelOpen,
                    }),
                    merge: (persistedState: unknown, currentState) => {
                        const persisted = isPersistedInstructionsState(
                            persistedState,
                        )
                            ? persistedState
                            : undefined;
                        const selectedTemplate =
                            persisted?.selectedTemplate !== undefined &&
                            getPlatformForFilename(
                                persisted.selectedTemplate,
                            ) === "internal" &&
                            getSectionIdForTemplate(
                                persisted.selectedTemplate,
                            ) !== undefined
                                ? persisted.selectedTemplate
                                : undefined;
                        const activeSectionId =
                            persisted?.activeSectionId !== undefined &&
                            getPlatformForSectionId(
                                persisted.activeSectionId,
                            ) === "internal"
                                ? persisted.activeSectionId
                                : selectedTemplate === undefined
                                  ? undefined
                                  : getSectionIdForTemplate(selectedTemplate);
                        const selectedVersionIdBySection =
                            persisted === undefined
                                ? currentState.selectedVersionIdBySection
                                : filterInternalSectionEntries(
                                      persisted.selectedVersionIdBySection,
                                  );
                        const isDefaultSelectedBySection =
                            persisted === undefined
                                ? currentState.isDefaultSelectedBySection
                                : filterInternalSectionEntries(
                                      persisted.isDefaultSelectedBySection,
                                  );
                        const selectedVersionId =
                            activeSectionId === undefined
                                ? undefined
                                : (selectedVersionIdBySection[
                                      activeSectionId
                                  ] ?? persisted?.selectedVersionId);
                        const isDefaultSelected =
                            activeSectionId === undefined
                                ? true
                                : (isDefaultSelectedBySection[
                                      activeSectionId
                                  ] ??
                                  persisted?.isDefaultSelected ??
                                  true);
                        const hasSeenGuide =
                            persisted?.hasSeenGuide ??
                            currentState.hasSeenGuide;

                        return {
                            ...currentState,
                            ...persisted,
                            activePlatform: "internal",
                            activeSectionId,
                            expandedSections:
                                persisted === undefined
                                    ? currentState.expandedSections
                                    : filterInternalSectionEntries(
                                          persisted.expandedSections,
                                      ),
                            selectedTemplate,
                            selectedVersionId,
                            selectedVersionIdBySection,
                            isDefaultSelected,
                            isDefaultSelectedBySection,
                            drafts:
                                persisted === undefined
                                    ? currentState.drafts
                                    : filterInternalTemplateEntries(
                                          persisted.drafts,
                                      ),
                            showGuide: !hasSeenGuide,
                        };
                    },
                },
            ),
        ),
    );
