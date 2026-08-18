import type { ChatDetailResponse } from "../types";

export interface GenerationAttemptRecord {
    generation_attempt_id: string;
    status: "pending" | "completed" | "failed";
    conversation_id: string;
    user_message_id?: string | null;
    assistant_message_id?: string | null;
}

export type GenerationAttemptReconciliation =
    | {
          status: "recovered";
          conversationId: string;
          detail: ChatDetailResponse;
      }
    | { status: "retryable"; conversationId: string }
    | { status: "pending"; conversationId: string }
    | { status: "unavailable"; error: unknown; conversationId?: string };

export const reconcileGenerationAttempt = async (
    loadAttempt: () => Promise<GenerationAttemptRecord>,
    loadConversationDetail: (
        conversationId: string,
        assistantMessageId: string,
    ) => Promise<ChatDetailResponse>,
): Promise<GenerationAttemptReconciliation> => {
    let attempt: GenerationAttemptRecord;
    try {
        attempt = await loadAttempt();
    } catch (error) {
        return { status: "unavailable", error };
    }

    if (attempt.status === "failed") {
        return {
            status: "retryable",
            conversationId: attempt.conversation_id,
        };
    }
    if (attempt.status === "pending") {
        return { status: "pending", conversationId: attempt.conversation_id };
    }

    const assistantMessageId = attempt.assistant_message_id;
    if (assistantMessageId === undefined || assistantMessageId === null) {
        return {
            status: "unavailable",
            conversationId: attempt.conversation_id,
            error: new TypeError("Completed generation attempt has no assistant message"),
        };
    }

    try {
        const detail = await loadConversationDetail(
            attempt.conversation_id,
            assistantMessageId,
        );
        if (!detail.messages.some((message) => message.id === assistantMessageId)) {
            throw new TypeError(
                "Completed generation attempt response is absent from conversation detail",
            );
        }
        return {
            status: "recovered",
            conversationId: attempt.conversation_id,
            detail,
        };
    } catch (error) {
        return {
            status: "unavailable",
            conversationId: attempt.conversation_id,
            error,
        };
    }
};
