import { Message as TranscriptMessage } from "@va/shared/components/message";
import type { ChatMessage } from "@va/shared/types";
import { type JSX, useEffect, useMemo, useRef, useState } from "react";

import { ConversationBranchSwitcher } from "../../chat/components/conversation-branch-navigation";
import { renderMessageTimestampFooter } from "../../chat/components/message-timestamp-footer";
import {
    type ConversationTreeMessage,
    convertConversationTree,
    hasMessageBranchAlternatives,
} from "../../chat/lib/conversation-tree";
import type { Message } from "../../chat/types";
import type { FlagDetail } from "../types";

export const ConversationTranscript = ({
    evidence,
    messages,
    targetId,
}: {
    evidence?: string;
    messages: FlagDetail["transcript"];
    targetId: string;
}): JSX.Element => {
    const tree = useMemo(
        () => convertConversationTree({ messages, current_branch_path: [] }),
        [messages],
    );
    const sourceById = useMemo(
        () => new Map(messages.map((message) => [message.id, message])),
        [messages],
    );
    const [selectedId, setSelectedId] = useState(targetId);
    const targetRef = useRef<HTMLDivElement | null>(null);
    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            const target = targetRef.current;
            const scrollTarget =
                target?.querySelector<HTMLElement>(
                    "mark[data-exact-highlight]",
                ) ?? target;
            scrollTarget?.scrollIntoView({
                behavior: "smooth",
                block: "nearest",
                inline: "nearest",
            });
        });
        return (): void => {
            cancelAnimationFrame(frame);
        };
    }, [evidence, targetId]);
    const path: ConversationTreeMessage[] = [];
    let current =
        tree.messagesById.get(selectedId) ?? tree.messagesById.get(targetId);
    while (current !== undefined) {
        path.unshift(current);
        current =
            current.parentId === undefined
                ? undefined
                : tree.messagesById.get(current.parentId);
    }
    // Continue through later messages, with the same chronological default as chat review.
    current = path.at(-1);
    while (current !== undefined) {
        const child = tree.childrenByParent.get(current.id)?.at(0);
        current =
            child === undefined ? undefined : tree.messagesById.get(child);
        if (current !== undefined) {
            path.push(current);
        }
    }
    const targetIndex = path.findIndex((message) => message.id === targetId);
    const handleSelectMessage = (id: string): boolean => {
        let candidate = tree.messagesById.get(id);
        while (candidate !== undefined && candidate.id !== targetId) {
            candidate =
                candidate.parentId === undefined
                    ? undefined
                    : tree.messagesById.get(candidate.parentId);
        }
        if (candidate?.id !== targetId) {
            return false;
        }
        setSelectedId(id);
        return true;
    };
    return (
        <div className="flex min-h-full flex-col px-4">
            <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-end gap-0">
                {path.map((message, index) => {
                    const source = sourceById.get(message.id);
                    const createdAt = new Date(
                        source?.created_at ?? "",
                    ).getTime();
                    const chatMessage: ChatMessage = {
                        id: message.id,
                        role: message.role,
                        content: message.content,
                        timestamp: createdAt,
                    };
                    const internalMessage: Message = {
                        id: message.id,
                        role: message.role,
                        content: message.content,
                        createdAt,
                        parentId: message.parentId,
                    };
                    const isTarget = message.id === targetId;
                    const canSwitchBranch =
                        targetIndex !== -1 &&
                        index > targetIndex &&
                        hasMessageBranchAlternatives(tree, message.id);
                    const footer = canSwitchBranch ? (
                        <ConversationBranchSwitcher
                            currentMessageId={message.id}
                            onSelectMessage={handleSelectMessage}
                            tree={tree}
                        />
                    ) : undefined;
                    return (
                        <div
                            aria-current={isTarget ? "true" : undefined}
                            key={message.id}
                            ref={isTarget ? targetRef : undefined}
                        >
                            <TranscriptMessage
                                footer={footer}
                                footerAside={renderMessageTimestampFooter(
                                    internalMessage,
                                )}
                                highlightExactSource={
                                    isTarget ? evidence : undefined
                                }
                                isPlayingTTS={false}
                                message={chatMessage}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
};
