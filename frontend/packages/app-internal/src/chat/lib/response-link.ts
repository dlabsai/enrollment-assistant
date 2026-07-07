export type ResponseLinkTarget = "chat" | "investigation";

interface ConversationLinkParams {
    conversationId: string;
    messageId?: string;
    target?: ResponseLinkTarget;
}

const getAppBaseUrl = (): string =>
    `${window.location.origin}${window.location.pathname}`;

export const getResponseLinkBaseUrl = (): string =>
    `${getAppBaseUrl()}${window.location.search}`;

const buildConversationHashPath = ({
    conversationId,
    messageId,
    target = "chat",
}: ConversationLinkParams): string => {
    const routeSegment = target === "investigation" ? "investigations" : "chats";
    const messageQuery =
        messageId === undefined || messageId === ""
            ? ""
            : `?message=${encodeURIComponent(messageId)}`;
    return `/${routeSegment}/${encodeURIComponent(conversationId)}${messageQuery}`;
};

export const openConversationInNewTab = (params: ConversationLinkParams): void => {
    window.open(
        `${getAppBaseUrl()}#${buildConversationHashPath(params)}`,
        "_blank",
        "noopener,noreferrer",
    );
};

export const buildResponseLink = (
    conversationId: string,
    messageId: string,
    target: ResponseLinkTarget = "chat",
): string =>
    `${getResponseLinkBaseUrl()}#${buildConversationHashPath({
        conversationId,
        messageId,
        target,
    })}`;
