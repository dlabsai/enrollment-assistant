import { useNavigate, useSearch } from "@tanstack/react-router";
import {
    Sheet,
    SheetContent,
    SheetTrigger,
} from "@va/shared/components/ui/sheet";
import { useSidebar } from "@va/shared/components/ui/sidebar";
import { UNIVERSITY_NAME } from "@va/shared/config";
import { useIsMobile } from "@va/shared/hooks/use-is-mobile";
import { setDocumentTitle } from "@va/shared/lib/document-title";
import { ExternalLink, Menu, PanelLeft, SquarePen } from "lucide-react";
import { type JSX, useEffect, useRef, useState } from "react";

import { useChatActions, useChatStore } from "../contexts/chat-store-context";
import { ChatStoreProvider } from "../contexts/chat-store-provider";
import type { ChatCollectionKind } from "../lib/api";
import { openConversationInNewTab } from "../lib/response-link";
import { ChatArea } from "./chat-area";
import { ChatList } from "./chat-list";

interface ChatPageProps {
    collectionKind?: ChatCollectionKind;
    routePath?: "/chat" | "/investigate";
    titleLabel?: string;
}

interface ChatPageContentProps {
    collectionKind?: ChatCollectionKind;
    routePath?: "/chat" | "/investigate";
    titleLabel?: string;
}

const MobileChatSheet = ({
    collectionKind = "chat",
    titleLabel = "chats",
}: {
    collectionKind?: ChatCollectionKind;
    titleLabel?: string;
}): JSX.Element => {
    const [open, setOpen] = useState(false);

    return (
        <Sheet
            onOpenChange={setOpen}
            open={open}
        >
            <SheetTrigger
                render={
                    <button
                        className="text-foreground hover:bg-accent hover:text-accent-foreground flex size-9 items-center justify-center rounded-full transition-colors"
                        type="button"
                    >
                        <Menu className="size-4" />
                        <span className="sr-only">Open {titleLabel}</span>
                    </button>
                }
            />
            <SheetContent
                className="w-64! max-w-none! overflow-x-hidden p-0"
                side="left"
            >
                <ChatList
                    className="h-full w-full border-r-0"
                    collectionKind={collectionKind}
                    onRequestClose={() => {
                        setOpen(false);
                    }}
                />
            </SheetContent>
        </Sheet>
    );
};

const ChatPageContent = ({
    collectionKind = "chat",
    routePath = "/chat",
    titleLabel = "Chat",
}: ChatPageContentProps): JSX.Element => {
    const chatsLoaded = useChatStore((state) => state.chatsLoaded);
    const currentChatId = useChatStore((state) => state.currentChatId);
    const currentChat = useChatStore((state) =>
        state.currentChatId === undefined
            ? undefined
            : state.chats.get(state.currentChatId),
    );
    const currentChatTitle = currentChat?.title;

    const search = useSearch({ from: routePath });
    const navigate = useNavigate({ from: routePath });
    const focusMessageId = "message" in search ? search.message : undefined;

    const { loadChats, selectChat, clearCurrentChat } = useChatActions();
    const { toggleSidebar } = useSidebar();
    const isMobile = useIsMobile();

    useEffect((): void => {
        if (!chatsLoaded) {
            void loadChats();
        }
    }, [chatsLoaded, loadChats]);

    useEffect(() => {
        const baseTitle = `${UNIVERSITY_NAME} Enrollment Assistant`;
        const chatTitle = currentChatTitle ?? "Untitled chat";
        setDocumentTitle(
            currentChatId === undefined
                ? `${titleLabel} · ${baseTitle}`
                : `${chatTitle} · ${titleLabel} · ${baseTitle}`,
        );
    }, [currentChatId, currentChatTitle, titleLabel]);

    const syncFromUrlRef = useRef(false);
    const lastSearchRef = useRef<string | undefined>(undefined);

    useEffect(() => {
        if (lastSearchRef.current === search.chat) {
            return;
        }
        lastSearchRef.current = search.chat;
        syncFromUrlRef.current = true;
        if (search.chat === undefined) {
            clearCurrentChat();
            return;
        }
        void selectChat(search.chat);
    }, [clearCurrentChat, search.chat, selectChat]);

    useEffect(() => {
        if (syncFromUrlRef.current) {
            if (currentChatId === search.chat) {
                syncFromUrlRef.current = false;
            }
            return;
        }
        if (currentChatId === search.chat) {
            return;
        }
        void navigate({
            search: () =>
                routePath === "/investigate"
                    ? { chat: currentChatId, message: undefined }
                    : {
                          chat: currentChatId,
                          platform: undefined,
                          userId: undefined,
                          userEmail: undefined,
                      },
            to: routePath,
        });
    }, [currentChatId, navigate, routePath, search.chat]);

    const canCreateChat = collectionKind === "chat";
    const canSendMessages = collectionKind === "chat" || currentChatId !== undefined;
    const itemLabel = collectionKind === "investigation" ? "investigation" : "chat";

    const handleNewChat = (): void => {
        clearCurrentChat();
    };

    const openSourceChat = (): void => {
        const sourceConversationId = currentChat?.investigationSourceConversationId;
        const sourceMessageId = currentChat?.investigationSourceMessageId;
        if (sourceConversationId === undefined) {
            return;
        }
        openConversationInNewTab({
            conversationId: sourceConversationId,
            messageId: sourceMessageId,
        });
    };

    return (
        <div className="flex h-full min-h-0 min-w-0 flex-1 overflow-hidden">
            <ChatList
                className="hidden md:flex"
                collectionKind={collectionKind}
            />

            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                <div className="flex items-center justify-between gap-2 px-3 py-2 md:hidden">
                    <div className="flex items-center gap-1">
                        <button
                            className="text-foreground hover:bg-accent hover:text-accent-foreground flex size-9 items-center justify-center rounded-full transition-colors"
                            onClick={toggleSidebar}
                            type="button"
                        >
                            <PanelLeft className="size-4" />
                            <span className="sr-only">Open sidebar</span>
                        </button>
                        {isMobile && (
                            <MobileChatSheet
                                collectionKind={collectionKind}
                                titleLabel={titleLabel.toLowerCase()}
                            />
                        )}
                    </div>
                    <div className="flex items-center gap-1">
                        {collectionKind === "investigation" &&
                            currentChat?.investigationSourceConversationId !== undefined && (
                                <button
                                    className="text-foreground hover:bg-accent hover:text-accent-foreground flex size-9 items-center justify-center rounded-full transition-colors"
                                    onClick={openSourceChat}
                                    type="button"
                                >
                                    <ExternalLink className="size-4" />
                                    <span className="sr-only">Open investigated chat</span>
                                </button>
                            )}
                        {canCreateChat && (
                            <button
                                className="text-foreground hover:bg-accent hover:text-accent-foreground flex size-9 items-center justify-center rounded-full transition-colors"
                                onClick={handleNewChat}
                                type="button"
                            >
                                <SquarePen className="size-4" />
                                <span className="sr-only">New {itemLabel}</span>
                            </button>
                        )}
                    </div>
                </div>

                {collectionKind === "investigation" &&
                    currentChat?.investigationSourceConversationId !== undefined && (
                        <div className="hidden shrink-0 justify-end border-b px-4 py-2 md:flex">
                            <button
                                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-2 rounded-md px-2 py-1 text-sm transition-colors"
                                onClick={openSourceChat}
                                type="button"
                            >
                                <ExternalLink className="size-4" />
                                Open investigated chat
                            </button>
                        </div>
                    )}

                <div className="min-h-0 flex-1">
                    <ChatArea
                        allowFeedback={collectionKind === "chat"}
                        allowInvestigations={collectionKind === "chat"}
                        canSendMessages={canSendMessages}
                        focusMessageId={focusMessageId}
                        modelSelectionMode={collectionKind}
                        responseLinkTarget={
                            collectionKind === "investigation" ? "investigation" : "chat"
                        }
                    />
                </div>
            </div>
        </div>
    );
};

export const ChatPage = ({
    collectionKind = "chat",
    routePath = "/chat",
    titleLabel = "Chat",
}: ChatPageProps): JSX.Element => (
    <ChatStoreProvider collectionKind={collectionKind}>
        <ChatPageContent
            collectionKind={collectionKind}
            routePath={routePath}
            titleLabel={titleLabel}
        />
    </ChatStoreProvider>
);

export const InvestigatePage = (): JSX.Element => (
    <ChatPage
        collectionKind="investigation"
        routePath="/investigate"
        titleLabel="Investigate"
    />
);
