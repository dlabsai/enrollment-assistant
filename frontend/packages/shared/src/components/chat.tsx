import { ErrorDialog } from "@va/shared/components/dialog";
import { useSTT } from "@va/shared/hooks/use-stt";
import { useTTS } from "@va/shared/hooks/use-tts";
import { markdownToPlainText } from "@va/shared/lib/markdown";
import { cn } from "@va/shared/lib/utils";
import type {
    ChatMessage,
    LoadingActivityItem,
    LoadingActivityLogEntry,
    LoadingIndicatorProps,
} from "@va/shared/types";
import {
    type JSX,
    type ReactNode,
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from "react";

import { InputBox } from "./input-box";
import { Messages } from "./messages";

interface ChatProps {
    messages: ChatMessage[];
    isLoading: boolean;
    onSendMessage: (message: string) => void;
    messagesInitialized?: boolean;
    canSendMessages?: boolean;
    headerContent?: ReactNode;
    disableVoiceFeatures?: boolean;
    emptyStateContent?: ReactNode;
    useNativeScrollbar?: boolean;
    contentWidthMode?: "standard" | "full";
    overlayComposer?: boolean;
    variant?: "default" | "public-widget";
    composerValue?: string;
    onComposerValueChange?: (value: string) => void;
    renderMessageFooter?: (message: ChatMessage) => ReactNode;
    renderMessageFooterAside?: (message: ChatMessage) => ReactNode;
    renderMessageBelowContent?: (message: ChatMessage) => ReactNode;
    hideMessageFooterUntilHover?: boolean;
    composerAccessory?: ReactNode;
    composerActionsAccessory?: ReactNode;
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
export const Chat = ({
    messages,
    isLoading,
    onSendMessage,
    messagesInitialized = true,
    canSendMessages = true,
    headerContent,
    disableVoiceFeatures = false,
    emptyStateContent,
    useNativeScrollbar = false,
    contentWidthMode = "full",
    overlayComposer = false,
    composerValue,
    onComposerValueChange,
    variant = "default",
    renderMessageFooter,
    renderMessageFooterAside,
    renderMessageBelowContent,
    hideMessageFooterUntilHover = false,
    composerAccessory,
    composerActionsAccessory,
    highlightQuery,
    highlightPhrase = false,
    focusMessageId,
    autoScroll = true,
    loadingMessages,
    loadingActivity,
    loadingActivityLog,
    loadingIndicatorVariant,
    loadingIndicatorComponent,
}: ChatProps): JSX.Element => {
    const resolvedHeaderContent = headerContent ?? undefined;
    const [alertDialogOpen, setAlertDialogOpen] = useState(false);
    const [alertMessage, setAlertMessage] = useState("");

    const [localComposerValue, setLocalComposerValue] = useState("");
    const resolvedComposerValue = composerValue ?? localComposerValue;
    const composerValueRef = useRef(resolvedComposerValue);

    const setComposerValue = useCallback(
        (next: string) => {
            if (onComposerValueChange) {
                onComposerValueChange(next);
            } else {
                setLocalComposerValue(next);
            }
        },
        [onComposerValueChange],
    );

    useEffect(() => {
        composerValueRef.current = resolvedComposerValue;
    }, [resolvedComposerValue]);

    const messagesRef = useRef(messages);
    useEffect(() => {
        messagesRef.current = messages;
    }, [messages]);

    const {
        speak: ttsSpeak,
        stop: ttsStop,
        playingMessageId,
    } = useTTS({
        preferredVoice: "Google US English",
        enabled: !disableVoiceFeatures,
    });

    const {
        start: sttStart,
        stop: sttStop,
        isRecording,
        supported: sttSupported,
    } = useSTT({
        enabled: !disableVoiceFeatures,
        continuous: true,
        lang: "en-US",
        onFinalTranscript: (chunk) => {
            const { current } = composerValueRef;
            const next = current ? `${current} ${chunk}` : chunk;
            setComposerValue(next);
        },
    });

    const handlePlayTTS = useCallback(
        (messageId: string) => {
            const message = messagesRef.current.find(
                (message) => message.id === messageId,
            );
            if (!message) {
                return;
            }

            if (playingMessageId === messageId) {
                ttsStop();
            } else {
                const plainText = markdownToPlainText(message.content);
                ttsSpeak(plainText, messageId);
            }
        },
        [playingMessageId, ttsStop, ttsSpeak],
    );

    const handleStartRecording = useCallback(() => {
        if (!sttSupported) {
            setAlertMessage(
                "Speech recognition is not supported in your browser.",
            );
            setAlertDialogOpen(true);
            return;
        }
        sttStart();
    }, [sttSupported, sttStart]);

    const contentContainerClassName = cn(
        "w-full",
        variant === "default" && "text-base md:text-base",
        contentWidthMode === "standard" && "mx-auto max-w-3xl",
    );

    const composerContainerClassName = cn(
        variant === "public-widget" ? "px-3 pt-1 pb-3" : "px-4 py-3",
    );

    const overlayRootRef = useRef<HTMLDivElement | null>(null);
    const composerRef = useRef<HTMLDivElement | null>(null);

    useLayoutEffect((): undefined | (() => void) => {
        if (!overlayComposer) {
            return undefined;
        }

        const overlayRoot = overlayRootRef.current;
        if (!overlayRoot) {
            return undefined;
        }

        const element = composerRef.current;
        if (!canSendMessages || !element) {
            overlayRoot.style.setProperty("--chat-composer-height", "0px");
            return undefined;
        }

        const updateComposerHeight = (): void => {
            const nextHeight = Math.ceil(
                element.getBoundingClientRect().height,
            );
            overlayRoot.style.setProperty(
                "--chat-composer-height",
                `${nextHeight}px`,
            );
        };

        const observer = new ResizeObserver(() => {
            updateComposerHeight();
        });

        observer.observe(element);
        updateComposerHeight();

        return () => {
            observer.disconnect();
        };
    }, [overlayComposer, canSendMessages]);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            {resolvedHeaderContent !== undefined && (
                <div className="border-b">{resolvedHeaderContent}</div>
            )}

            {overlayComposer ? (
                <div
                    className="relative min-h-0 flex-1"
                    ref={overlayRootRef}
                >
                    <div
                        className="absolute top-0 right-0 left-0"
                        style={{ bottom: "var(--chat-composer-height, 0px)" }}
                    >
                        <Messages
                            autoScroll={autoScroll}
                            bottomPaddingPx={0}
                            contentContainerClassName={
                                contentContainerClassName
                            }
                            emptyStateContent={emptyStateContent}
                            focusMessageId={focusMessageId}
                            hideMessageFooterUntilHover={
                                hideMessageFooterUntilHover
                            }
                            highlightPhrase={highlightPhrase}
                            highlightQuery={highlightQuery}
                            isLoading={isLoading}
                            loadingActivity={loadingActivity}
                            loadingActivityLog={loadingActivityLog}
                            loadingIndicatorComponent={
                                loadingIndicatorComponent
                            }
                            loadingIndicatorVariant={loadingIndicatorVariant}
                            loadingMessages={loadingMessages}
                            messages={messages}
                            messagesInitialized={messagesInitialized}
                            onPlayTTS={
                                disableVoiceFeatures ? undefined : handlePlayTTS
                            }
                            playingMessageId={playingMessageId}
                            renderMessageBelowContent={
                                renderMessageBelowContent
                            }
                            renderMessageFooter={renderMessageFooter}
                            renderMessageFooterAside={renderMessageFooterAside}
                            useNativeScrollbar={useNativeScrollbar}
                            variant={variant}
                        />
                    </div>

                    {canSendMessages && (
                        <div
                            className="pointer-events-none absolute right-0 bottom-0 left-0"
                            ref={composerRef}
                        >
                            <div
                                className={cn(
                                    "bg-background pt-0 pb-4",
                                    variant === "public-widget"
                                        ? "px-3"
                                        : "px-4",
                                )}
                                data-slot="chat-composer-container"
                            >
                                <div
                                    className={cn(
                                        "pointer-events-auto",
                                        contentContainerClassName,
                                    )}
                                >
                                    <InputBox
                                        accessory={composerAccessory}
                                        actionsAccessory={
                                            composerActionsAccessory
                                        }
                                        disabled={!canSendMessages}
                                        isLoading={isLoading}
                                        isRecording={
                                            sttSupported ? isRecording : false
                                        }
                                        onSend={onSendMessage}
                                        onValueChange={setComposerValue}
                                        variant={variant}
                                        {...(sttSupported && {
                                            onStartRecording:
                                                handleStartRecording,
                                            onStopRecording: sttStop,
                                        })}
                                        showSTTButton={sttSupported}
                                        value={resolvedComposerValue}
                                    />
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                <>
                    <div className="min-h-0 flex-1 overflow-hidden">
                        <Messages
                            autoScroll={autoScroll}
                            contentContainerClassName={
                                contentContainerClassName
                            }
                            emptyStateContent={emptyStateContent}
                            focusMessageId={focusMessageId}
                            hideMessageFooterUntilHover={
                                hideMessageFooterUntilHover
                            }
                            highlightPhrase={highlightPhrase}
                            highlightQuery={highlightQuery}
                            isLoading={isLoading}
                            loadingActivity={loadingActivity}
                            loadingActivityLog={loadingActivityLog}
                            loadingIndicatorComponent={
                                loadingIndicatorComponent
                            }
                            loadingIndicatorVariant={loadingIndicatorVariant}
                            loadingMessages={loadingMessages}
                            messages={messages}
                            messagesInitialized={messagesInitialized}
                            onPlayTTS={
                                disableVoiceFeatures ? undefined : handlePlayTTS
                            }
                            playingMessageId={playingMessageId}
                            renderMessageBelowContent={
                                renderMessageBelowContent
                            }
                            renderMessageFooter={renderMessageFooter}
                            renderMessageFooterAside={renderMessageFooterAside}
                            useNativeScrollbar={useNativeScrollbar}
                            variant={variant}
                        />
                    </div>
                    {canSendMessages && (
                        <div
                            className={composerContainerClassName}
                            data-slot="chat-composer-container"
                        >
                            <div className={contentContainerClassName}>
                                <InputBox
                                    accessory={composerAccessory}
                                    actionsAccessory={composerActionsAccessory}
                                    disabled={!canSendMessages}
                                    isLoading={isLoading}
                                    isRecording={
                                        sttSupported ? isRecording : false
                                    }
                                    onSend={onSendMessage}
                                    onValueChange={setComposerValue}
                                    variant={variant}
                                    {...(sttSupported && {
                                        onStartRecording: handleStartRecording,
                                        onStopRecording: sttStop,
                                    })}
                                    showSTTButton={sttSupported}
                                    value={resolvedComposerValue}
                                />
                            </div>
                        </div>
                    )}
                </>
            )}

            <ErrorDialog
                description={alertMessage}
                okLabel="OK"
                onOpenChange={setAlertDialogOpen}
                open={alertDialogOpen}
                title="Notice"
            />
        </div>
    );
};
