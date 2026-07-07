import { Chat } from "@va/shared/components/chat";
import { LoadingIndicator } from "@va/shared/components/loading-indicator";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import type { ChatMessage } from "@va/shared/types";
import { SquarePen } from "lucide-react";
import { type JSX, useEffect, useState } from "react";

import {
    useInstructionsActions,
    useInstructionsStore,
    useInstructionsStoreSubscribe,
} from "../contexts/instructions-store-context";
import { useTestChat } from "../hooks/use-test-chat";
import {
    getSectionIdForScope,
    INTERNAL_PROMPT_PLATFORM,
} from "../lib/sections";
import type { PromptSetVersionListItem } from "../types";

const EMPTY_VERSIONS: PromptSetVersionListItem[] = [];
const INTERNAL_ASSISTANT_SECTION_ID = getSectionIdForScope(
    "assistant",
    INTERNAL_PROMPT_PLATFORM,
);

const VersionSelector = (): JSX.Element => {
    const versions = useInstructionsStore(
        (state) =>
            state.versionsBySection[INTERNAL_ASSISTANT_SECTION_ID] ??
            EMPTY_VERSIONS,
    );
    const testChatVersionId = useInstructionsStore(
        (state) => state.testChatVersionId,
    );

    const selectedVersion = versions.find(
        (version) => version.id === testChatVersionId,
    );
    const selectedVersionLabel =
        selectedVersion === undefined
            ? undefined
            : `v${selectedVersion.version_number} – ${selectedVersion.name}`;

    const { setTestChatVersion } = useInstructionsActions();

    return (
        <Select
            onValueChange={(versionId) => {
                if (versionId === null) {
                    return;
                }

                setTestChatVersion(versionId);
            }}
            value={testChatVersionId}
        >
            <SelectTrigger className="w-full">
                <SelectValue placeholder="Choose Version...">
                    {selectedVersionLabel}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {versions.length === 0 ? (
                    <div className="text-muted-foreground px-2 py-4 text-center text-sm">
                        No versions yet. Create one in the Instructions Editor.
                    </div>
                ) : (
                    versions.map((version) => (
                        <SelectItem
                            key={version.id}
                            value={version.id}
                        >
                            <span className="flex items-center gap-2">
                                v{version.version_number} – {version.name}
                                {version.is_deployed && (
                                    <Badge className="bg-status-live text-status-live-foreground">
                                        Live
                                    </Badge>
                                )}
                            </span>
                        </SelectItem>
                    ))
                )}
            </SelectContent>
        </Select>
    );
};

interface TestChatControlsProps {
    onNewChat?: () => void;
    showNewChat: boolean;
}

export const TestChatControls = ({
    onNewChat,
    showNewChat,
}: TestChatControlsProps): JSX.Element => (
    <div className="flex items-center gap-3">
        <div className="min-w-[200px] flex-1">
            <VersionSelector />
        </div>
        {showNewChat && (
            <Button
                onClick={onNewChat}
                size="sm"
                variant="outline"
            >
                <SquarePen className="mr-1 size-3" />
                New chat
            </Button>
        )}
    </div>
);

export const TestChatInfo = (): JSX.Element | undefined => {
    const versions = useInstructionsStore(
        (state) =>
            state.versionsBySection[INTERNAL_ASSISTANT_SECTION_ID] ??
            EMPTY_VERSIONS,
    );
    const testChatVersionId = useInstructionsStore(
        (state) => state.testChatVersionId,
    );

    const selectedVersion = versions.find(
        (version) => version.id === testChatVersionId,
    );

    if (selectedVersion === undefined) {
        return undefined;
    }

    const description = selectedVersion.description?.trim();

    return (
        <span className="text-muted-foreground min-w-0 truncate text-sm">
            {description !== undefined && description !== "" && (
                <span>{description} • </span>
            )}
            {selectedVersion.created_by_name} •{" "}
            {selectedVersion.modified_prompt_count} modified
        </span>
    );
};

interface TestChatProps {
    onNewChatReady?: (handler: () => void) => void;
    onMessagesChange?: (hasMessages: boolean) => void;
}

export const TestChat = ({
    onNewChatReady,
    onMessagesChange,
}: TestChatProps): JSX.Element => {
    const versions = useInstructionsStore(
        (state) =>
            state.versionsBySection[INTERNAL_ASSISTANT_SECTION_ID] ??
            EMPTY_VERSIONS,
    );
    const testChatVersionId = useInstructionsStore(
        (state) => state.testChatVersionId,
    );
    const testChatChatId = useInstructionsStore(
        (state) => state.testChatChatId,
    );
    const testChatParentMessageId = useInstructionsStore(
        (state) => state.testChatParentMessageId,
    );

    const { setTestChatChat, clearTestChat } = useInstructionsActions();
    const subscribe = useInstructionsStoreSubscribe();

    const [messages, setMessages] = useState<ChatMessage[]>([]);

    const handleAddMessage = (message: ChatMessage): void => {
        setMessages((prev) => [...prev, message]);
    };

    const handleChatChange = (
        newChatId: string,
        newParentMessageId?: string,
    ): void => {
        setTestChatChat(newChatId, newParentMessageId);
    };

    const { isLoading, sendMessage } = useTestChat({
        chatId: testChatChatId,
        parentMessageId: testChatParentMessageId,
        onChatChange: handleChatChange,
        onAddMessage: handleAddMessage,
        promptSetVersionId:
            testChatVersionId === "" ? undefined : testChatVersionId,
    });

    const handleSendMessage = (message: string): void => {
        void sendMessage(message);
    };

    // Subscribe to version changes - clear messages when version changes
    // Uses subscribeWithSelector to only trigger when testChatVersionId changes
    useEffect(() => {
        const unsubscribe = subscribe(
            (state) => state.testChatVersionId,
            () => {
                setMessages([]);
                clearTestChat();
            },
        );
        return unsubscribe;
    }, [subscribe, clearTestChat]);

    useEffect(() => {
        if (!onNewChatReady) {
            return;
        }

        const handleNewChat = (): void => {
            setMessages([]);
            clearTestChat();
        };

        onNewChatReady(handleNewChat);
    }, [clearTestChat, onNewChatReady]);

    useEffect(() => {
        onMessagesChange?.(messages.length > 0);
    }, [messages.length, onMessagesChange]);

    if (!testChatVersionId) {
        return (
            <div className="bg-background flex h-full flex-col">
                <div className="flex flex-1 items-center justify-center p-6">
                    <Card className="w-full max-w-md">
                        <CardHeader>
                            <CardTitle>Select a version to test</CardTitle>
                            <CardDescription>
                                {versions.length === 0
                                    ? "Create a version in the Instructions Editor first."
                                    : "Choose a version from the dropdown above."}
                            </CardDescription>
                        </CardHeader>
                    </Card>
                </div>
            </div>
        );
    }

    return (
        <Chat
            disableVoiceFeatures
            isLoading={isLoading}
            loadingIndicatorComponent={LoadingIndicator}
            messages={messages}
            onSendMessage={handleSendMessage}
        />
    );
};
