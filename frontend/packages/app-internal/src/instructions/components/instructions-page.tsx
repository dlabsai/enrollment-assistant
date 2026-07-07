import { Button } from "@va/shared/components/ui/button";
import { ChevronRight } from "lucide-react";
import { type JSX, useEffect, useRef, useState } from "react";

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
import { TestChat, TestChatControls, TestChatInfo } from "./test-chat";

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

interface TestChatPanelProps {
    onNewChat: () => void;
    onMessagesChange: (hasMessages: boolean) => void;
    onNewChatReady: (handler: () => void) => void;
    showNewChat: boolean;
}

const TestChatPanel = ({
    onNewChat,
    onMessagesChange,
    onNewChatReady,
    showNewChat,
}: TestChatPanelProps): JSX.Element | undefined => {
    const isChatPanelOpen = useInstructionsStore(
        (state) => state.isChatPanelOpen,
    );
    const activeSectionId = useInstructionsStore(
        (state) => state.activeSectionId,
    );
    const { setChatPanelOpen } = useInstructionsActions();

    if (!isChatPanelOpen || !isAssistantSectionId(activeSectionId)) {
        return undefined;
    }

    return (
        <div className="bg-background text-foreground flex min-h-0 w-full flex-col border-t md:w-[380px] md:border-t-0 md:border-l">
            <div className="border-b px-3 py-2">
                <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">Test Chat</span>
                    <Button
                        onClick={() => {
                            setChatPanelOpen(false);
                        }}
                        size="icon"
                        variant="ghost"
                    >
                        <ChevronRight className="size-4" />
                        <span className="sr-only">Collapse test chat</span>
                    </Button>
                </div>
            </div>
            <div className="border-b px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                    <TestChatControls
                        onNewChat={onNewChat}
                        showNewChat={showNewChat}
                    />
                    <TestChatInfo />
                </div>
            </div>
            <div className="min-h-0 flex-1">
                <TestChat
                    onMessagesChange={onMessagesChange}
                    onNewChatReady={onNewChatReady}
                />
            </div>
        </div>
    );
};

const InstructionsWorkspace = (): JSX.Element => {
    const [testChatHasMessages, setTestChatHasMessages] = useState(false);
    const testChatNewChatRef = useRef<(() => void) | undefined>(undefined);

    return (
        <div className="bg-background text-foreground flex h-full flex-col">
            <ErrorBanner />
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
                <div className="hidden md:flex">
                    <InstructionsSidebar />
                </div>
                <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                    <EditorArea />
                </div>
                <TestChatPanel
                    onMessagesChange={setTestChatHasMessages}
                    onNewChat={() => {
                        testChatNewChatRef.current?.();
                    }}
                    onNewChatReady={(handler) => {
                        testChatNewChatRef.current = handler;
                    }}
                    showNewChat={testChatHasMessages}
                />
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
