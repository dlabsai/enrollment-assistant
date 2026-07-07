import { ScrollArea } from "@va/shared/components/ui/scroll-area";
import { WelcomeMessage } from "@va/shared/components/welcome-message";
import { cn } from "@va/shared/lib/utils";
import type {
    ChatMessage,
    LoadingActivityItem,
    LoadingActivityLogEntry,
    LoadingIndicatorProps,
} from "@va/shared/types";
import { ArrowDown } from "lucide-react";
import {
    type JSX,
    type ReactNode,
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react";

import { Message } from "./message";

interface MessagesProps {
    messages: ChatMessage[];
    isLoading: boolean;
    playingMessageId?: string;
    onPlayTTS?: (messageId: string) => void;
    messagesInitialized: boolean;
    emptyStateContent?: ReactNode;
    useNativeScrollbar?: boolean;
    contentContainerClassName?: string;
    bottomPaddingPx?: number;
    renderMessageFooter?: (message: ChatMessage) => ReactNode;
    renderMessageFooterAside?: (message: ChatMessage) => ReactNode;
    renderMessageBelowContent?: (message: ChatMessage) => ReactNode;
    hideMessageFooterUntilHover?: boolean;
    variant?: "default" | "public-widget";
    highlightQuery?: string;
    highlightPhrase?: boolean;
    focusMessageId?: string;
    autoScroll?: boolean;
    loadingMessages?: string[];
    loadingActivity?: LoadingActivityItem[];
    loadingActivityLog?: LoadingActivityLogEntry[];
    loadingIndicatorVariant?: "default" | "shimmer" | "ai-elements";
    loadingIndicatorComponent: (
        props: LoadingIndicatorProps,
    ) => JSX.Element | undefined;
}

export const Messages = ({
    messages,
    isLoading,
    playingMessageId,
    onPlayTTS,
    messagesInitialized,
    emptyStateContent,
    useNativeScrollbar = false,
    contentContainerClassName,
    bottomPaddingPx = 0,
    renderMessageFooter,
    renderMessageFooterAside,
    renderMessageBelowContent,
    hideMessageFooterUntilHover = false,
    variant = "default",
    highlightQuery = "",
    highlightPhrase = false,
    focusMessageId,
    autoScroll = true,
    loadingMessages,
    loadingActivity,
    loadingActivityLog,
    loadingIndicatorVariant,
    loadingIndicatorComponent: LoadingIndicatorComponent,
}: MessagesProps): JSX.Element => {
    // Reserve some whitespace below the last message at all times (ChatGPT-style).
    // When the loader appears (and later its delayed text), it should render inside
    // this reserved area instead of pushing the chat upward.
    const reservedBottomSpacePx = variant === "public-widget" ? 48 : 96;
    const bottomSpacePx = reservedBottomSpacePx + bottomPaddingPx;

    // Spec: treat the user as "at bottom" unless they've scrolled up > 100px.
    const nearBottomThresholdPx = 100;

    const viewportRef = useRef<HTMLDivElement | undefined>(undefined);
    const messageRefsRef = useRef<Record<string, HTMLDivElement | undefined>>(
        {},
    );
    const prevMessageCountRef = useRef(0);
    const wasLoadingRef = useRef(false);
    const [loadingTrigger, setLoadingTrigger] = useState(0);
    const [isNearBottom, setIsNearBottom] = useState(true);
    const isNearBottomRef = useRef(true);
    const [viewportNodeVersion, setViewportNodeVersion] = useState(0);
    const [flashMessageId, setFlashMessageId] = useState<string | undefined>();
    const shouldScrollOnChatOpenRef = useRef(true);
    // Scrollability and measurements
    const [isScrollable, setIsScrollable] = useState(false);
    const contentRootRef = useRef<HTMLDivElement | null>(null);

    const prevViewportElRef = useRef<HTMLDivElement | undefined>(undefined);

    const setMessageRef = (
        id: string,
        element: HTMLDivElement | null,
    ): void => {
        messageRefsRef.current[id] = element ?? undefined;
    };
    const setViewportRef = useCallback(
        (element: HTMLDivElement | null): void => {
            const next = element ?? undefined;
            if (prevViewportElRef.current !== next) {
                viewportRef.current = next;
                prevViewportElRef.current = next;
                setViewportNodeVersion((prevVersion) => prevVersion + 1);
            }
        },
        [],
    );
    const computeNearBottom = useCallback((): void => {
        const viewport = viewportRef.current;
        if (!viewport) {
            return;
        }

        // Consider the user "near bottom" unless they've scrolled up meaningfully.
        const distance =
            viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
        const next = distance <= nearBottomThresholdPx;

        isNearBottomRef.current = next;
        setIsNearBottom((prev) => (prev === next ? prev : next));
    }, [nearBottomThresholdPx]);

    // Reset refs when chat changes (detected by first message ID changing)
    const firstMessageId = messages[0]?.id ?? undefined;
    useEffect(() => {
        if (!autoScroll) {
            return;
        }
        prevMessageCountRef.current = 0;
        wasLoadingRef.current = false;
        shouldScrollOnChatOpenRef.current = true;
    }, [autoScroll, firstMessageId]);

    // Open/switch chats: always scroll instantly to last user message (spec).
    // This runs once the scroll viewport is available (important for ScrollArea).
    useEffect(() => {
        if (!autoScroll) {
            return;
        }
        if (!shouldScrollOnChatOpenRef.current) {
            return;
        }
        if (messages.length === 0) {
            return;
        }

        requestAnimationFrame(() => {
            if (!shouldScrollOnChatOpenRef.current) {
                return;
            }

            const viewport = viewportRef.current;
            if (!viewport) {
                return;
            }

            const lastUserMessage = messages
                .toReversed()
                .find((message) => message.role === "user");
            if (!lastUserMessage) {
                shouldScrollOnChatOpenRef.current = false;
                computeNearBottom();
                return;
            }

            const el = messageRefsRef.current[lastUserMessage.id];
            if (!el) {
                // Refs not ready yet; try again on next render/viewport change.
                return;
            }

            const containerRect = viewport.getBoundingClientRect();
            const elementRect = el.getBoundingClientRect();
            const scrollOffset =
                elementRect.top - containerRect.top + viewport.scrollTop - 16;

            viewport.scrollTo({
                top: scrollOffset,
                behavior: "auto",
            });

            shouldScrollOnChatOpenRef.current = false;
            computeNearBottom();
        });
    }, [
        autoScroll,
        firstMessageId,
        messages,
        viewportNodeVersion,
        computeNearBottom,
    ]);

    useEffect((): (() => void) | undefined => {
        if (focusMessageId === undefined || messages.length === 0) {
            return undefined;
        }

        let timeout: ReturnType<typeof setTimeout> | null = null;
        const frame = requestAnimationFrame(() => {
            const viewport = viewportRef.current;
            const element = messageRefsRef.current[focusMessageId];
            if (!viewport || !element) {
                return;
            }

            const containerRect = viewport.getBoundingClientRect();
            const elementRect = element.getBoundingClientRect();
            const scrollOffset =
                elementRect.top - containerRect.top + viewport.scrollTop - 24;

            viewport.scrollTo({
                top: scrollOffset,
                behavior: "smooth",
            });
            setFlashMessageId(focusMessageId);
            timeout = setTimeout(() => {
                setFlashMessageId((current) =>
                    current === focusMessageId ? undefined : current,
                );
            }, 3000);
        });

        return () => {
            cancelAnimationFrame(frame);
            if (timeout !== null) {
                clearTimeout(timeout);
            }
        };
    }, [focusMessageId, messages.length, viewportNodeVersion]);

    // Track "near bottom" via scroll metrics
    useEffect((): undefined | (() => void) => {
        const viewport = viewportRef.current;
        if (!viewport) {
            return undefined;
        }

        const onScroll = (): void => {
            computeNearBottom();
        };

        viewport.addEventListener("scroll", onScroll, { passive: true });

        const frame = requestAnimationFrame(() => {
            computeNearBottom();
        });

        return () => {
            cancelAnimationFrame(frame);
            viewport.removeEventListener("scroll", onScroll);
        };
    }, [computeNearBottom, viewportNodeVersion]);

    // Track whether content overflows (scrollable)
    useEffect((): undefined | (() => void) => {
        const viewport = viewportRef.current;
        const content = contentRootRef.current;
        if (!viewport || !content) {
            return undefined;
        }

        const computeScrollable = (): void => {
            const next = viewport.scrollHeight - viewport.clientHeight > 1;
            setIsScrollable((prev) => (prev === next ? prev : next));

            computeNearBottom();
        };

        const viewportRO = new ResizeObserver(computeScrollable);
        const contentRO = new ResizeObserver(computeScrollable);
        viewportRO.observe(viewport);
        contentRO.observe(content);

        const frame = requestAnimationFrame(() => {
            computeScrollable();
        });

        return () => {
            cancelAnimationFrame(frame);
            viewportRO.disconnect();
            contentRO.disconnect();
        };
    }, [computeNearBottom, messages.length, viewportNodeVersion]);

    // Track when isLoading was true (for smooth scrolling assistant messages)
    useEffect(() => {
        if (isLoading) {
            wasLoadingRef.current = true;
        }
    }, [isLoading]);

    useEffect(() => {
        if (!autoScroll) {
            return;
        }
        // If we're opening/switching chats, the dedicated effect above will handle
        // the required instant scroll (and it needs the viewport to be ready). Avoid
        // running the smooth-scroll logic here during that phase.
        if (shouldScrollOnChatOpenRef.current) {
            prevMessageCountRef.current = messages.length;
            return;
        }

        if (
            prevMessageCountRef.current !== messages.length &&
            messages.length > 0
        ) {
            // Smooth scroll during active chat interaction:
            // - isLoading is true (waiting for response)
            // - OR wasLoading was true (assistant message just arrived)
            // Instant scroll for everything else (loading chat history, switching chats)
            const isActiveChatFlow = isLoading || wasLoadingRef.current;
            const scrollBehavior = isActiveChatFlow ? "smooth" : "auto";

            // Reset wasLoading after using it (one-time use for assistant message scroll)
            if (!isLoading && wasLoadingRef.current) {
                wasLoadingRef.current = false;
            }

            // Active chat flow: scroll to last user message with 16px gap.
            // Use requestAnimationFrame to ensure the DOM has painted.
            requestAnimationFrame((): void => {
                const viewport = viewportRef.current;
                if (!viewport) {
                    return;
                }

                const lastUserMessage = messages
                    .toReversed()
                    .find((message) => message.role === "user");
                if (!lastUserMessage) {
                    return;
                }

                const el = messageRefsRef.current[lastUserMessage.id];
                if (!el) {
                    return;
                }

                const containerRect = viewport.getBoundingClientRect();
                const elementRect = el.getBoundingClientRect();
                const scrollOffset =
                    elementRect.top -
                    containerRect.top +
                    viewport.scrollTop -
                    16;

                viewport.scrollTo({
                    top: scrollOffset,
                    behavior: scrollBehavior,
                });
            });
        }

        prevMessageCountRef.current = messages.length;
    }, [autoScroll, messages, isLoading]);

    const handleLoadingTextShow = (): void => {
        setLoadingTrigger((value) => value + 1);
    };

    // Scroll to bottom when loading indicator text messages appear (after delay)
    // Only scroll if user hasn't scrolled up (isNearBottom) - don't interrupt their reading
    const prevLoadingTriggerRef = useRef(0);
    useEffect(() => {
        if (!autoScroll) {
            return;
        }
        if (!isLoading || !isNearBottom) {
            return;
        }

        // Only scroll if loadingTrigger actually changed (not on initial render)
        if (loadingTrigger === prevLoadingTriggerRef.current) {
            prevLoadingTriggerRef.current = loadingTrigger;
            return;
        }
        prevLoadingTriggerRef.current = loadingTrigger;

        if (viewportRef.current) {
            viewportRef.current.scrollTo({
                top: viewportRef.current.scrollHeight,
                behavior: "smooth",
            });
        }
    }, [autoScroll, loadingTrigger, isLoading, isNearBottom]);

    const scrollToBottom = (): void => {
        if (viewportRef.current) {
            viewportRef.current.scrollTo({
                top: viewportRef.current.scrollHeight,
                behavior: "smooth",
            });
        }
    };

    const content = (
        <div className="px-4 pt-4">
            <div
                className={cn(
                    "flex min-h-0 flex-col",
                    contentContainerClassName,
                )}
                ref={contentRootRef}
            >
                <div className="flex min-h-0 flex-col gap-0">
                    {messages.length === 0 &&
                        !isLoading &&
                        messagesInitialized &&
                        (emptyStateContent ?? <WelcomeMessage />)}
                    {messages.map((message) => (
                        <div
                            className={cn(
                                "rounded-xl transition-[background-color,box-shadow] duration-700",
                                flashMessageId === message.id &&
                                    "bg-yellow-100/70 shadow-[0_0_0_2px_rgba(250,204,21,0.65)] dark:bg-yellow-950/40",
                            )}
                            key={message.id}
                            ref={(element) => {
                                setMessageRef(message.id, element);
                            }}
                        >
                            <Message
                                belowContent={
                                    renderMessageBelowContent
                                        ? renderMessageBelowContent(message)
                                        : undefined
                                }
                                footer={
                                    renderMessageFooter
                                        ? renderMessageFooter(message)
                                        : undefined
                                }
                                footerAside={
                                    renderMessageFooterAside
                                        ? renderMessageFooterAside(message)
                                        : undefined
                                }
                                hideFooterUntilHover={
                                    hideMessageFooterUntilHover
                                }
                                highlightPhrase={highlightPhrase}
                                highlightQuery={highlightQuery}
                                isPlayingTTS={playingMessageId === message.id}
                                message={message}
                                onPlayTTS={onPlayTTS}
                            />
                        </div>
                    ))}
                </div>

                {/* Reserved bottom area: always present; loader renders inside it. */}
                <div
                    aria-hidden={!isLoading}
                    style={{ minHeight: `${bottomSpacePx}px` }}
                >
                    <LoadingIndicatorComponent
                        activityItems={loadingActivity}
                        activityLog={loadingActivityLog}
                        isVisible={isLoading}
                        messages={loadingMessages}
                        onTextShow={handleLoadingTextShow}
                        variant={loadingIndicatorVariant}
                    />
                </div>
            </div>
        </div>
    );

    return (
        <div className="relative h-full">
            {useNativeScrollbar ? (
                <div
                    className="h-full overflow-auto"
                    ref={setViewportRef}
                    style={{ scrollbarGutter: "stable both-edges" }}
                >
                    {content}
                </div>
            ) : (
                <ScrollArea
                    className="h-full"
                    viewportRef={setViewportRef}
                >
                    {content}
                </ScrollArea>
            )}
            {/* Scroll to bottom button - fades in/out */}
            <button
                aria-hidden={!(isScrollable && !isNearBottom)}
                aria-label="Scroll to bottom"
                className={cn(
                    "bg-background/80 text-muted-foreground hover:bg-background hover:text-foreground border-border absolute bottom-4 left-1/2 flex h-8 w-8 -translate-x-1/2 items-center justify-center rounded-full border shadow-sm backdrop-blur-sm transition-opacity duration-350",
                    isScrollable && !isNearBottom
                        ? "opacity-100"
                        : "pointer-events-none opacity-0",
                )}
                onClick={scrollToBottom}
                tabIndex={isScrollable && !isNearBottom ? 0 : -1}
                type="button"
            >
                <ArrowDown size={16} />
            </button>
        </div>
    );
};
