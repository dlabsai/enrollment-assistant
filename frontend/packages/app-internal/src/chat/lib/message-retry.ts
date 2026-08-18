import type {
    DraftPromptTemplate,
    Message,
    MessageRetryRequest,
    ModelOverrides,
} from "../types";

export interface CreateMessageRetryRequestInput {
    content: string;
    modelOverrides?: ModelOverrides;
    parentMessageId: string | null | undefined;
    isRegeneration: boolean;
    trimToMessageId: string | null | undefined;
    draftPromptTemplates?: DraftPromptTemplate[];
}

export const createMessageRetryRequest = ({
    content,
    modelOverrides,
    parentMessageId,
    isRegeneration,
    trimToMessageId,
    draftPromptTemplates,
}: CreateMessageRetryRequestInput): MessageRetryRequest => ({
    content,
    modelOverrides:
        modelOverrides === undefined ? undefined : { ...modelOverrides },
    options: {
        parentMessageId,
        isRegeneration: isRegeneration || undefined,
        trimToMessageId: isRegeneration
            ? trimToMessageId
            : parentMessageId,
        draftPromptTemplates: draftPromptTemplates?.map((template) => ({
            ...template,
        })),
    },
});

export const trimMessagesToMessageId = (
    messages: Message[],
    messageId: string | null | undefined,
): Message[] => {
    if (messageId === undefined) {
        return messages;
    }
    if (messageId === null) {
        return [];
    }
    const trimIndex = messages.findIndex((message) => message.id === messageId);
    return trimIndex === -1 ? messages : messages.slice(0, trimIndex + 1);
};
