import { Chat } from "@va/shared/components/chat";
import { DEFAULT_LOADING_MESSAGES } from "@va/shared/components/loading-messages";
import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import { UNIVERSITY_NAME } from "@va/shared/config";
import { useIsMobile } from "@va/shared/hooks/use-is-mobile";
import { setDocumentTitle } from "@va/shared/lib/document-title";
import { logger } from "@va/shared/lib/logger";
import { cn } from "@va/shared/lib/utils";
import { MessageCircle } from "lucide-react";
import { type JSX, useCallback, useEffect, useRef, useState } from "react";

import { LoadingIndicator } from "@/components/loading-indicator";

import { VISIBLE_BY_DEFAULT } from "../config";
import { useChat } from "../hooks/use-chat";
import { submitConsentData, submitConsentForCurrentChat } from "../lib/consent-api";
import { getConsentData, hasCompleteConsentData } from "../lib/storage";
import { ConsentBanner } from "./consent-banner";
import { Footer } from "./footer";
import { Header } from "./header";

const CHAT_WIDGET_ID = "chat-widget";
const CHAT_HISTORY_KEY = "chat_history";

const handleConsentSubmit = (chatId: string): void => {
    const consentData = getConsentData();
    if (consentData === undefined) {
        return;
    }

    const submit = async (): Promise<void> => {
        const result = await submitConsentData(consentData, chatId);
        if (!result.success) {
            logger.error("Failed to submit consent data:", result.error);
        }
    };

    void submit();
};

export const PublicApp = (): JSX.Element => {
    const [open, setOpen] = useState(() => VISIBLE_BY_DEFAULT);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [chatKey, setChatKey] = useState(0);
    const [isVisible, setIsVisible] = useState(() => VISIBLE_BY_DEFAULT);
    const [shouldRender, setShouldRender] = useState(() => VISIBLE_BY_DEFAULT);
    const [consentGiven, setConsentGiven] = useState(() => hasCompleteConsentData());
    // Public widget is a fixed-width panel; only go full-screen on small phones.
    const isMobile = useIsMobile(480);
    const visibilityTimeoutRef = useRef<
        ReturnType<typeof setTimeout> | undefined
    >(undefined);
    const visibilityFrameRef = useRef<number | undefined>(undefined);

    const { messages, isLoading, sendMessage, resetChat } = useChat({
        consentGiven,
        onConsentSubmit: handleConsentSubmit,
    });

    useEffect(() => {
        setDocumentTitle(`${UNIVERSITY_NAME} Enrollment Assistant`);
    }, []);

    const clearVisibilityTimers = useCallback(() => {
        if (visibilityTimeoutRef.current !== undefined) {
            clearTimeout(visibilityTimeoutRef.current);
            visibilityTimeoutRef.current = undefined;
        }
        if (visibilityFrameRef.current !== undefined) {
            cancelAnimationFrame(visibilityFrameRef.current);
            visibilityFrameRef.current = undefined;
        }
    }, []);

    const handleOpen = useCallback(() => {
        clearVisibilityTimers();
        setOpen(true);

        setShouldRender(true);
        visibilityFrameRef.current = requestAnimationFrame(() => {
            setIsVisible(true);
            visibilityFrameRef.current = undefined;
        });
    }, [clearVisibilityTimers]);

    const handleClose = useCallback(() => {
        clearVisibilityTimers();
        setOpen(false);
        setIsVisible(false);
        visibilityTimeoutRef.current = setTimeout(() => {
            setShouldRender(false);
            visibilityTimeoutRef.current = undefined;
        }, 300);

        if (consentGiven) {
            void submitConsentForCurrentChat();
        }
    }, [clearVisibilityTimers, consentGiven]);

    const handleConsentAccept = useCallback(() => {
        setConsentGiven(true);
    }, []);

    const handleConsentDecline = useCallback(() => {
        setConsentGiven(false);
        handleClose();
    }, [handleClose]);

    useEffect(
        () => (): void => {
            clearVisibilityTimers();
        },
        [clearVisibilityTimers],
    );

    const handleConfirmReset = (): void => {
        localStorage.setItem(
            CHAT_HISTORY_KEY,
            JSON.stringify({
                messages: [],
                chatId: undefined,
                parentMessageId: undefined,
            }),
        );
        resetChat();
        setChatKey((prevKey) => prevKey + 1);
        setIsModalOpen(false);
    };

    const handleSendMessage = useCallback(
        (message: string) => {
            void sendMessage(message);
        },
        [sendMessage],
    );

    const chatPanelClasses = cn(
        "fixed z-50 flex min-h-0 flex-col overflow-hidden border bg-card text-card-foreground shadow-2xl transition-all duration-300 ease-out font-widget text-widget",
        isMobile
            ? "bottom-4 top-4 left-1/2 w-[min(402px,calc(100vw-2rem))] -translate-x-1/2 rounded-[16px]"
            : "bottom-6 right-6 h-[min(720px,calc(100vh-3rem))] w-[402px] rounded-[16px]",
        isVisible ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0",
    );

    return (
        <div className="public">
            {!open && !shouldRender && (
                <button
                    aria-controls={CHAT_WIDGET_ID}
                    aria-expanded={open}
                    aria-label="Open enrollment assistant"
                    className="bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring/40 font-widget text-widget fixed right-6 bottom-6 z-40 flex items-center gap-2 rounded-full px-5 py-3 text-sm font-semibold shadow-lg shadow-black/20 transition focus-visible:ring-2 focus-visible:outline-none"
                    onClick={handleOpen}
                    type="button"
                >
                    <MessageCircle
                        aria-hidden="true"
                        className="size-5"
                    />
                    <span>Chat</span>
                </button>
            )}

            {shouldRender && (
                <section
                    aria-label={`${UNIVERSITY_NAME} enrollment assistant`}
                    aria-modal={isMobile}
                    className={chatPanelClasses}
                    id={CHAT_WIDGET_ID}
                    role="dialog"
                >
                    <Header
                        onClose={handleClose}
                        onReset={() => {
                            setIsModalOpen(true);
                        }}
                    />
                    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                        <div className="min-h-0 flex-1 overflow-hidden">
                            {consentGiven ? (
                                <Chat
                                    isLoading={isLoading}
                                    key={chatKey}
                                    loadingIndicatorComponent={LoadingIndicator}
                                    loadingMessages={DEFAULT_LOADING_MESSAGES}
                                    messages={messages}
                                    onSendMessage={handleSendMessage}
                                    variant="public-widget"
                                />
                            ) : (
                                <div className="flex h-full overflow-y-auto p-4">
                                    <div className="m-auto">
                                        <ConsentBanner
                                            onAccept={handleConsentAccept}
                                            onDecline={handleConsentDecline}
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                        {consentGiven && <Footer />}
                    </div>
                </section>
            )}

            <Dialog
                modal={false}
                onOpenChange={(open) => {
                    if (!open) {
                        setIsModalOpen(false);
                    }
                }}
                open={isModalOpen}
            >
                <DialogContent
                    className="font-widget text-widget"
                    showCloseButton={false}
                >
                    <DialogHeader>
                        <DialogTitle>Clear Chat History</DialogTitle>
                        <DialogDescription>
                            Are you sure you want to clear the chat history?
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button
                            onClick={() => {
                                setIsModalOpen(false);
                            }}
                            size="sm"
                            variant="outline"
                        >
                            Cancel
                        </Button>
                        <Button
                            onClick={handleConfirmReset}
                            size="sm"
                        >
                            Confirm
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
};
