import { Button } from "@va/shared/components/ui/button";
import { SquarePen } from "lucide-react";
import { type JSX, memo, useCallback, useEffect } from "react";

import { ChatArea } from "../../chat/components/chat-area";
import {
    useChatActions,
    useChatStore,
    useChatStoreApi,
} from "../../chat/contexts/chat-store-context";
import { ChatStoreProvider } from "../../chat/contexts/chat-store-provider";
import { selectCurrentChat } from "../../chat/lib/store";
import {
    useInstructionsStore,
    useInstructionsStoreApi,
} from "../contexts/instructions-store-context";
import { buildAssistantDraftPromptTemplates } from "../lib/assistant-draft";

const MemoChatArea = memo(ChatArea);

const useCanTestDraft = (): boolean =>
    useInstructionsStore(
        (state) =>
            state.diskTemplatesLoaded &&
            (state.selectedVersionId === undefined ||
                state.selectedVersionDetail?.id === state.selectedVersionId),
    );

const TestChatControls = (): JSX.Element => {
    const instructionsStore = useInstructionsStoreApi();
    const currentChatId = useChatStore((state) => state.currentChatId);
    const { abortChat, clearCurrentChat, setDraft } = useChatActions();

    const resetTestChat = (): void => {
        if (currentChatId !== undefined) {
            abortChat(currentChatId);
            setDraft(currentChatId, "");
        }
        clearCurrentChat();
        setDraft(undefined, "");
        instructionsStore.getState().setTestChatState(undefined);
    };

    return (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-muted-foreground min-w-0 text-sm">
                If you changed instructions, click New chat to test the latest instructions.
            </span>
            <Button
                onClick={resetTestChat}
                size="sm"
                type="button"
                variant="outline"
            >
                <SquarePen data-icon="inline-start" />
                New chat
            </Button>
        </div>
    );
};

const TestChatBody = (): JSX.Element => {
    const instructionsStore = useInstructionsStoreApi();
    const canTestDraft = useCanTestDraft();
    const statusMessage = canTestDraft
        ? undefined
        : "Loading selected instructions…";

    const getDraftPromptTemplates = useCallback(
        () => buildAssistantDraftPromptTemplates(instructionsStore.getState()),
        [instructionsStore],
    );

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            {statusMessage !== undefined && (
                <div className="bg-muted/40 text-muted-foreground border-b px-3 py-2 text-sm">
                    {statusMessage}
                </div>
            )}
            <div className="min-h-0 flex-1 overflow-hidden">
                <MemoChatArea
                    allowInvestigations={false}
                    canSendMessages={canTestDraft}
                    getDraftPromptTemplates={getDraftPromptTemplates}
                />
            </div>
        </div>
    );
};

const TestChatContent = (): JSX.Element => {
    const instructionsStore = useInstructionsStoreApi();
    const chatStore = useChatStoreApi();
    const showControls = useChatStore(
        (state) => (selectCurrentChat(state)?.messages.length ?? 0) > 0,
    );

    useEffect(() => {
        let mounted = true;

        const persistCurrentDraftChat = (): void => {
            const chatState = chatStore.getState();
            const chatId = chatState.currentChatId;
            if (chatId === undefined || chatId.startsWith("__temp_")) {
                return;
            }

            const chat = chatState.chats.get(chatId);
            if (chat?.promptSource !== "draft") {
                return;
            }

            const instructionsState = instructionsStore.getState();
            if (instructionsState.testChatId === chatId) {
                return;
            }

            instructionsState.setTestChatState(chatId);
        };

        const restorePersistedTestChat = (): void => {
            const { testChatId } = instructionsStore.getState();
            if (
                testChatId === undefined ||
                chatStore.getState().currentChatId !== undefined
            ) {
                return;
            }

            void chatStore
                .getState()
                .selectChat(testChatId)
                .then(() => {
                    if (!mounted) {
                        return;
                    }
                    const chat = chatStore.getState().chats.get(testChatId);
                    if (chat?.promptSource !== "draft") {
                        chatStore.getState().clearCurrentChat();
                        instructionsStore.getState().setTestChatState(undefined);
                        return;
                    }
                    persistCurrentDraftChat();
                });
        };

        const unsubscribeChat = chatStore.subscribe((): void => {
            if (mounted) {
                persistCurrentDraftChat();
            }
        });

        restorePersistedTestChat();
        queueMicrotask((): void => {
            if (mounted) {
                persistCurrentDraftChat();
            }
        });

        return (): void => {
            mounted = false;
            unsubscribeChat();
        };
    }, [chatStore, instructionsStore]);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            {showControls && (
                <div className="border-b px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <TestChatControls />
                    </div>
                </div>
            )}
            <div className="min-h-0 flex-1 overflow-hidden">
                <TestChatBody />
            </div>
        </div>
    );
};

export const TestChat = (): JSX.Element => (
    <ChatStoreProvider>
        <TestChatContent />
    </ChatStoreProvider>
);
