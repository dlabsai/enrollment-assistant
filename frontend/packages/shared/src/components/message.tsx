import { splitHighlightText } from "@va/shared/lib/highlight";
import { cn } from "@va/shared/lib/utils";
import type { ChatMessage } from "@va/shared/types";
import type { Element, Parent, Root, Text } from "hast";
import { decodeString } from "micromark-util-decode-string";
import { memo, type ReactNode, useMemo } from "react";
import { Streamdown } from "streamdown";
import type { Pluggable, Plugin } from "unified";
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
    highlightExactSource?: string;
    isFocusHighlighted?: boolean;
}

const isElement = (node: Parent): node is Element => node.type === "element";

const findUniqueSource = (
    source: string,
    query: string | undefined,
): number | undefined => {
    if (query === undefined || query === "") {
        return undefined;
    }
    const start = source.indexOf(query);
    return start !== -1 && !source.includes(query, start + 1) ? start : undefined;
};

interface HighlightPluginOptions {
    query: string;
    highlightClassName: string;
    phrase: boolean;
    sourceStart?: number;
}

const sourceHighlightRange = (
    node: Text,
    source: string,
    sourceStart: number,
    sourceEnd: number,
): [start: number, end: number] | undefined => {
    const nodeStart = node.position?.start.offset;
    const nodeEnd = node.position?.end.offset;
    if (
        nodeStart === undefined ||
        nodeEnd === undefined ||
        nodeEnd <= sourceStart ||
        nodeStart >= sourceEnd
    ) {
        return undefined;
    }
    const overlapStart = Math.max(nodeStart, sourceStart);
    const overlapEnd = Math.min(nodeEnd, sourceEnd);
    if (sourceStart <= nodeStart && sourceEnd >= nodeEnd) {
        return [0, node.value.length];
    }
    const nodeSource = source.slice(nodeStart, nodeEnd);
    if (decodeString(nodeSource) !== node.value) {
        return undefined;
    }
    return [
        decodeString(nodeSource.slice(0, overlapStart - nodeStart)).length,
        decodeString(nodeSource.slice(0, overlapEnd - nodeStart)).length,
    ];
};

interface HighlightTextPart {
    text: string;
    highlight: boolean;
}

const splitSourceHighlightText = (
    node: Text,
    source: string,
    sourceStart: number,
    sourceEnd: number,
): HighlightTextPart[] => {
    const range = sourceHighlightRange(node, source, sourceStart, sourceEnd);
    if (!range) {
        return [];
    }
    return [
        { text: node.value.slice(0, range[0]), highlight: false },
        { text: node.value.slice(range[0], range[1]), highlight: true },
        { text: node.value.slice(range[1]), highlight: false },
    ].filter((part) => part.text !== "");
};

const highlightRehypePlugin: Plugin<[HighlightPluginOptions], Root> =
    ({ query, highlightClassName, phrase, sourceStart }) =>
    (tree: Root, file): void => {
        const source = String(file.value);
        const sourceEnd =
            sourceStart === undefined ? undefined : sourceStart + query.length;
        const isSourceHighlight = sourceStart !== undefined;
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

                const parts =
                    sourceStart === undefined || sourceEnd === undefined
                        ? splitHighlightText(node.value, query, phrase)
                        : splitSourceHighlightText(
                              node,
                              source,
                              sourceStart,
                              sourceEnd,
                          );
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
                                ...(isSourceHighlight
                                    ? { "data-exact-highlight": true }
                                    : {}),
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

const createHighlightRehypePlugin = (
    query: string,
    highlightClassName: string,
    phrase = false,
    sourceStart?: number,
): Pluggable | undefined => {
    const resolvedQuery = sourceStart === undefined ? query.trim() : query;
    if (resolvedQuery === "") {
        return undefined;
    }

    // Streamdown caches processors by plugin function name plus serialized options.
    // Supplying the query and source range as options prevents stale highlighting.
    return [
        highlightRehypePlugin,
        {
            query: resolvedQuery,
            highlightClassName,
            phrase,
            sourceStart,
        },
    ];
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
        highlightExactSource,
        isFocusHighlighted = false,
    }: MessageProps) => {
        const isUser = message.role === "user";
        const shouldHideFooter = hideFooterUntilHover && !isUser;
        const shouldHideUserFooter = isUser;
        const showFooterRow =
            footer !== undefined ||
            footerAside !== undefined ||
            (!isUser && onPlayTTS !== undefined);
        const exactSourceStart = findUniqueSource(
            message.content,
            highlightExactSource,
        );
        const resolvedHighlightQuery =
            highlightExactSource === undefined
                ? highlightQuery
                : exactSourceStart === undefined
                  ? ""
                  : highlightExactSource;

        const highlightRehypePlugin = useMemo(
            () =>
                createHighlightRehypePlugin(
                    resolvedHighlightQuery,
                    DEFAULT_HIGHLIGHT_CLASS,
                    highlightPhrase,
                    exactSourceStart,
                ),
            [exactSourceStart, highlightPhrase, resolvedHighlightQuery],
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
                    key={`${message.id}-${resolvedHighlightQuery}-${highlightPhrase}-${exactSourceStart ?? ""}`}
                    mode={exactSourceStart === undefined ? undefined : "static"}
                    rehypePlugins={
                        highlightRehypePlugin
                            ? [highlightRehypePlugin]
                            : undefined
                    }
                >
                    {message.content}
                </Streamdown>
            );
        }, [
            exactSourceStart,
            highlightPhrase,
            highlightQuery,
            highlightRehypePlugin,
            isUser,
            message,
            resolvedHighlightQuery,
        ]);

        return (
            <div
                className={cn(
                    "flex rounded-xl transition-[background-color,box-shadow] duration-700",
                    isUser ? "mb-0 justify-end" : "mb-6 justify-start",
                    isFocusHighlighted &&
                        "bg-yellow-100/70 shadow-[0_0_0_2px_rgba(250,204,21,0.65)] dark:bg-yellow-950/40",
                )}
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
