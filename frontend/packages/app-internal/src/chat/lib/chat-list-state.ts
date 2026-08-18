import type { Chat, ChatListItem } from "../types";

export const mergeChatListItems = (
    items: readonly ChatListItem[],
    existingChats: ReadonlyMap<string, Chat>,
): Map<string, Chat> => {
    const chats = new Map<string, Chat>();

    for (const item of items) {
        const metadata = {
            id: item.id,
            title: item.title ?? undefined,
            summary: item.summary ?? undefined,
            lastMessagePreview: item.last_message_preview ?? undefined,
            updatedAt: new Date(item.updated_at).getTime(),
            isPublic: item.is_public,
            promptSource: item.prompt_source ?? undefined,
            userName: item.user_name ?? undefined,
            userEmail: item.user_email ?? undefined,
        };
        const existingChat = existingChats.get(item.id);
        chats.set(
            item.id,
            existingChat === undefined
                ? {
                      ...metadata,
                      messages: [],
                      isLoading: false,
                      hasUnread: false,
                  }
                : { ...existingChat, ...metadata },
        );
    }

    return chats;
};
