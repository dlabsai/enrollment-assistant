import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import { type JSX, useEffect } from "react";

import {
    useInstructionsActions,
    useInstructionsStore,
} from "../contexts/instructions-store-context";
import { InstructionsStoreProvider } from "../contexts/instructions-store-provider";
import {
    getSectionIdForScope,
    INTERNAL_PROMPT_PLATFORM,
    isAssistantSectionId,
} from "../lib/sections";
import { ConfirmDialogs } from "./confirm-dialogs";
import { EditorArea } from "./editor-area";
import { HelpGuide } from "./help-guide";
import { InstructionsSidebar } from "./instructions-sidebar";
import { InstructionsToolbar } from "./instructions-toolbar";
import { TestChat } from "./test-chat";

const ErrorBanner = (): JSX.Element | undefined => {
    const error = useInstructionsStore((state) => state.error);
    const { clearError } = useInstructionsActions();

    if (error === undefined) {
        return undefined;
    }

    return (
        <div className="bg-destructive/10 text-destructive border-destructive mx-4 mt-4 rounded-md border p-3 text-sm">
            {error}
            <button
                className="ml-2 font-medium underline"
                onClick={clearError}
                type="button"
            >
                Dismiss
            </button>
        </div>
    );
};

const TestChatPanel = (): JSX.Element => (
    <div className="bg-background text-foreground flex h-full min-h-0 w-full flex-col overflow-hidden border-l">
        <div className="min-h-0 flex-1 overflow-hidden">
            <TestChat />
        </div>
    </div>
);

const InstructionsWorkspace = (): JSX.Element => {
    const isChatPanelOpen = useInstructionsStore(
        (state) => state.isChatPanelOpen,
    );
    const activeSectionId = useInstructionsStore(
        (state) => state.activeSectionId,
    );
    const showTestChat = isChatPanelOpen && isAssistantSectionId(activeSectionId);

    return (
        <div className="bg-background text-foreground flex h-full flex-col">
            <ErrorBanner />
            <div className="flex min-h-0 flex-1 overflow-hidden">
                <div className="hidden md:flex">
                    <InstructionsSidebar />
                </div>
                <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                    <InstructionsToolbar />
                    <div className="min-h-0 flex-1 overflow-hidden">
                        {showTestChat ? (
                            <ResizablePanelGroup
                                className="min-h-0"
                                orientation="horizontal"
                            >
                                <ResizablePanel
                                    defaultSize="50%"
                                    minSize="22%"
                                    style={{ overflow: "visible" }}
                                >
                                    <div className="flex h-full min-w-0 flex-col overflow-hidden">
                                        <EditorArea />
                                    </div>
                                </ResizablePanel>
                                <ResizableHandle
                                    className="mx-2"
                                    withHandle
                                />
                                <ResizablePanel
                                    defaultSize="50%"
                                    minSize="22%"
                                    style={{ overflow: "visible" }}
                                >
                                    <div className="flex h-full min-w-0 flex-col overflow-hidden">
                                        <TestChatPanel />
                                    </div>
                                </ResizablePanel>
                            </ResizablePanelGroup>
                        ) : (
                            <div className="flex h-full min-w-0 flex-col overflow-hidden">
                                <EditorArea />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

const InstructionsPageContent = (): JSX.Element => {
    const activeSectionId = useInstructionsStore(
        (state) => state.activeSectionId,
    );
    const diskTemplatesLoaded = useInstructionsStore(
        (state) => state.diskTemplatesLoaded,
    );
    const versionsLoaded = useInstructionsStore(
        (state) => state.versionsLoadedBySection,
    );
    const selectedVersionId = useInstructionsStore(
        (state) => state.selectedVersionId,
    );
    const selectedVersionDetail = useInstructionsStore(
        (state) => state.selectedVersionDetail,
    );

    const {
        loadDiskTemplates,
        loadVersions,
        loadDeployedVersion,
        loadVersionDetail,
    } = useInstructionsActions();

    useEffect(() => {
        if (!diskTemplatesLoaded) {
            void loadDiskTemplates();
        }
    }, [diskTemplatesLoaded, loadDiskTemplates]);

    useEffect(() => {
        const internalSectionId = getSectionIdForScope(
            "assistant",
            INTERNAL_PROMPT_PLATFORM,
        );
        if (!versionsLoaded[internalSectionId]) {
            void loadVersions(internalSectionId);
        }
    }, [versionsLoaded, loadVersions]);

    useEffect(() => {
        if (activeSectionId === undefined) {
            return;
        }
        if (!versionsLoaded[activeSectionId]) {
            void loadVersions(activeSectionId);
        }
        void loadDeployedVersion(activeSectionId);
    }, [activeSectionId, loadDeployedVersion, loadVersions, versionsLoaded]);

    useEffect(() => {
        if (selectedVersionId === undefined) {
            return;
        }
        if (selectedVersionDetail?.id === selectedVersionId) {
            return;
        }
        void loadVersionDetail(selectedVersionId);
    }, [loadVersionDetail, selectedVersionDetail?.id, selectedVersionId]);

    return (
        <div className="flex flex-1 flex-col overflow-hidden">
            <HelpGuide />
            <InstructionsWorkspace />
            <ConfirmDialogs />
        </div>
    );
};

export const InstructionsPage = (): JSX.Element => (
    <InstructionsStoreProvider>
        <InstructionsPageContent />
    </InstructionsStoreProvider>
);
