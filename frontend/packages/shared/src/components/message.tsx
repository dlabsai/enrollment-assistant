import { splitHighlightText } from "@va/shared/lib/highlight";
import type { ChatMessage } from "@va/shared/types";
import type { Element, Parent, Root, Text } from "hast";
import { memo, type ReactNode, useMemo } from "react";
import { Streamdown } from "streamdown";
import type { Pluggable } from "unified";
import { visit } from "unist-util-visit";

import { DEFAULT_HIGHLIGHT_CLASS, HighlightedText } from "./highlighted-text";
import { TTSButton } from "./tts-button";

interface MessageProps {
    message: ChatMessage;
    isPlayingTTS: boolean;
    onPlayTTS?: (messageId: string) => void;
    footer?: ReactNode;
    footerAside?: ReactNode;
    belowContent?: ReactNode;
    hideFooterUntilHover?: boolean;
    highlightQuery?: string;
    highlightPhrase?: boolean;
}

const isElement = (node: Parent): node is Element => node.type === "element";

const createHighlightRehypePlugin = (
    query: string,
    highlightClassName: string,
    phrase = false,
): Pluggable | undefined => {
    const trimmedQuery = query.trim();
    if (trimmedQuery === "") {
        return undefined;
    }

    return () => (tree: Root) => {
        visit(
            tree,
            "text",
            (
                node: Text,
                index: number | undefined,
                parent: Parent | undefined,
            ) => {
                if (!parent || typeof index !== "number") {
                    return;
                }

                if (isElement(parent) && parent.tagName === "mark") {
                    return;
                }

                const parts = splitHighlightText(node.value, trimmedQuery, phrase);
                const hasHighlights = parts.some((part) => part.highlight);
                if (!hasHighlights) {
                    return;
                }

                const nextNodes = parts.map((part) => {
                    if (part.highlight) {
                        const highlightNode: Element = {
                            type: "element",
                            tagName: "mark",
                            properties: {
                                className: highlightClassName,
                            },
                            children: [{ type: "text", value: part.text }],
                        };
                        return highlightNode;
                    }

                    const textNode: Text = {
                        type: "text",
                        value: part.text,
                    };
                    return textNode;
                });

                parent.children.splice(index, 1, ...nextNodes);
            },
        );
    };
};

export const Message = memo(
    ({
        message,
        isPlayingTTS,
        onPlayTTS,
        footer,
        footerAside,
        belowContent,
        hideFooterUntilHover = false,
        highlightQuery = "",
        highlightPhrase = false,
    }: MessageProps) => {
        const isUser = message.role === "user";
        const shouldHideFooter = hideFooterUntilHover && !isUser;
        const shouldHideUserFooter = isUser;
        const showFooterRow =
            footer !== undefined ||
            footerAside !== undefined ||
            (!isUser && onPlayTTS !== undefined);

        const highlightRehypePlugin = useMemo(
            () =>
                createHighlightRehypePlugin(
                    highlightQuery,
                    DEFAULT_HIGHLIGHT_CLASS,
                    highlightPhrase,
                ),
            [highlightPhrase, highlightQuery],
        );

        const content = useMemo(() => {
            if (!message.content) {
                return <p>Error: Message content missing</p>;
            }

            if (isUser) {
                return (
                    <div className="max-w-none wrap-break-word whitespace-normal">
                        <p>
                            <HighlightedText
                                phrase={highlightPhrase}
                                query={highlightQuery}
                                text={message.content}
                            />
                        </p>
                    </div>
                );
            }

            return (
                <Streamdown
                    className="max-w-none wrap-break-word"
                    key={`${message.id}-${highlightQuery}-${highlightPhrase}`}
                    rehypePlugins={
                        highlightRehypePlugin
                            ? [highlightRehypePlugin]
                            : undefined
                    }
                >
                    {message.content}
                </Streamdown>
            );
        }, [highlightPhrase, highlightQuery, highlightRehypePlugin, isUser, message]);

        return (
            <div
                className={`flex ${isUser ? "justify-end" : "justify-start"} ${isUser ? "mb-0" : "mb-6"}`}
            >
                <div
                    className={
                        isUser
                            ? "group flex max-w-[80%] flex-col items-end"
                            : shouldHideFooter
                              ? "group w-full"
                              : "w-full"
                    }
                >
                    <div
                        className={
                            isUser
                                ? "bg-muted text-foreground w-fit rounded-[24px] px-4 py-2"
                                : undefined
                        }
                    >
                        {content}
                    </div>
                    {showFooterRow ? (
                        <>
                            <div
                                className={
                                    shouldHideUserFooter
                                        ? "mt-1 flex h-6 min-h-6 flex-nowrap items-center gap-1 overflow-hidden opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
                                        : shouldHideFooter
                                          ? "mt-2 flex w-full flex-wrap items-center gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
                                          : "mt-2 flex w-full flex-wrap items-center gap-1"
                                }
                            >
                                <div className="flex flex-wrap items-center gap-1">
                                    {footer}
                                    {isUser ||
                                    onPlayTTS === undefined ? undefined : (
                                        <TTSButton
                                            isPlaying={isPlayingTTS}
                                            onClick={() => {
                                                onPlayTTS(message.id);
                                            }}
                                        />
                                    )}
                                </div>
                                {footerAside === undefined ? undefined : (
                                    <div className="text-muted-foreground text-xs">
                                        {footerAside}
                                    </div>
                                )}
                            </div>
                            {isUser ? <div className="h-4" /> : undefined}
                        </>
                    ) : isUser ? (
                        <>
                            <div className="mt-1 h-6 min-h-6" />
                            <div className="h-4" />
                        </>
                    ) : undefined}
                    {belowContent !== undefined && belowContent !== null ? (
                        <div className="mt-2">{belowContent}</div>
                    ) : undefined}
                </div>
            </div>
        );
    },
);

Message.displayName = "Message";
