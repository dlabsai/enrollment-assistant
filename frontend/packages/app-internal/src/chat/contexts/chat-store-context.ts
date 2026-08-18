import { createContext, use } from "react";
import { useStore } from "zustand";

import type { ChatActions, ChatStore, ChatStoreState } from "../lib/store";

export const ChatStoreContext = createContext<ChatStore | undefined>(undefined);

const useChatStoreContext = (): ChatStore => {
    const value = use(ChatStoreContext);
    if (value === undefined) {
        throw new Error("useChatStore must be used within ChatStoreProvider");
    }
    return value;
};

export const useChatStoreApi = (): ChatStore => useChatStoreContext();

export const useChatStore = <T>(selector: (state: ChatStoreState) => T): T => {
    const store = useChatStoreContext();
    return useStore(store, selector);
};

/**
 * Get all actions.
 * Action references are stable, but this hook returns a new object each render.
 * Avoid using the returned object as a prop or effect dependency.
 */
export const useChatActions = (): ChatActions => {
    const store = useChatStoreContext();
    // Access actions directly from store state - they're stable references
    const state = store.getState();
    return {
        loadChats: state.loadChats,
        selectChat: state.selectChat,
        loadConversationTree: state.loadConversationTree,
        setActiveBranch: state.setActiveBranch,
        clearCurrentChat: state.clearCurrentChat,
        abortChat: state.abortChat,
        sendMessage: state.sendMessage,
        retryMessage: state.retryMessage,
        retryGroundingSources: state.retryGroundingSources,
        deleteChat: state.deleteChat,
        renameChatTitle: state.renameChatTitle,
        regenerateChatTitle: state.regenerateChatTitle,
        markCurrentAsRead: state.markCurrentAsRead,
        setDraft: state.setDraft,
        updateChat: state.updateChat,
        loadMessageFeedback: state.loadMessageFeedback,
        initializeMessageFeedback: state.initializeMessageFeedback,
        loadMessageActivityLog: state.loadMessageActivityLog,
        submitMessageFeedback: state.submitMessageFeedback,
        removeMessageFeedback: state.removeMessageFeedback,
    };
};
