import type { ChatDetailResponse } from "../../chat/types";

export const formatChatTranscript = (detail: ChatDetailResponse): string =>
    detail.messages
        .map((message) => {
            const label = message.role === "assistant" ? "Assistant" : "User";
            const content =
                message.guardrails_blocked === true &&
                typeof message.guardrails_blocked_message === "string" &&
                message.guardrails_blocked_message !== ""
                    ? message.guardrails_blocked_message
                    : message.content;
            return `${label}:\n${content.trimEnd()}`;
        })
        .join("\n\n---\n\n");
