import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@va/shared/components/ui/popover";
import { Textarea } from "@va/shared/components/ui/textarea";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { MessageSquareText, ThumbsDown, ThumbsUp, Users } from "lucide-react";
import { type JSX, useEffect, useMemo, useState } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import { useChatActions, useChatStore } from "../contexts/chat-store-context";
import type { MessageFeedback as MessageFeedbackEntry, Rating } from "../types";

const emptyFeedbackList: MessageFeedbackEntry[] = [];

interface OtherFeedbacksPopoverProps {
    feedbacks: MessageFeedbackEntry[];
}

const OtherFeedbacksPopover = ({
    feedbacks,
}: OtherFeedbacksPopoverProps): JSX.Element => {
    const thumbsUpCount = feedbacks.filter(
        (item) => item.rating === "thumbs_up",
    ).length;
    const thumbsDownCount = feedbacks.filter(
        (item) => item.rating === "thumbs_down",
    ).length;

    return (
        <Popover>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <PopoverTrigger
                            render={
                                <Button
                                    aria-label={`${formatLocaleNumber(feedbacks.length)} other feedback${feedbacks.length === 1 ? "" : "s"}`}
                                    className="text-muted-foreground rounded-full transition"
                                    size="icon-sm"
                                    type="button"
                                    variant="ghost"
                                >
                                    <Users
                                        aria-hidden="true"
                                        className="size-4"
                                    />
                                    <span className="sr-only">
                                        {formatLocaleNumber(feedbacks.length)} other feedback
                                        {feedbacks.length === 1 ? "" : "s"}
                                    </span>
                                </Button>
                            }
                        />
                    }
                />
                <TooltipContent>
                    {formatLocaleNumber(feedbacks.length)} other feedback
                    {feedbacks.length === 1 ? "" : "s"}
                    {thumbsUpCount > 0 && ` (${thumbsUpCount} positive)`}
                    {thumbsDownCount > 0 && ` (${thumbsDownCount} negative)`}
                </TooltipContent>
            </Tooltip>
            <PopoverContent
                align="start"
                className="w-80"
            >
                <div className="space-y-3">
                    <h4 className="font-medium">Other Feedback</h4>
                    <ul className="space-y-2">
                        {feedbacks.map((item) => (
                            <li
                                className="flex items-start gap-2 text-sm"
                                key={item.id}
                            >
                                {item.rating === "thumbs_up" ? (
                                    <ThumbsUp className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                                ) : (
                                    <ThumbsDown className="text-destructive mt-0.5 size-4 shrink-0" />
                                )}
                                <div className="min-w-0 flex-1">
                                    <span className="font-medium">
                                        {item.user_name}
                                    </span>
                                    {item.text !== undefined &&
                                        item.text.trim() !== "" && (
                                            <p className="text-muted-foreground mt-0.5 break-words">
                                                {item.text}
                                            </p>
                                        )}
                                </div>
                            </li>
                        ))}
                    </ul>
                </div>
            </PopoverContent>
        </Popover>
    );
};

interface MessageFeedbackProps {
    messageId: string;
    isEligible?: boolean;
    feedbackSource?: "chat" | "chats";
    hideOtherFeedbacksPopover?: boolean;
    onFeedbackChange?: (change: { previous?: Rating; next?: Rating }) => void;
}

interface MessageFeedbackDetailsProps {
    messageId: string;
    isEligible?: boolean;
}

export const MessageFeedbackDetails = ({
    messageId,
    isEligible = true,
}: MessageFeedbackDetailsProps): JSX.Element | undefined => {
    const feedbackList = useChatStore(
        (state) => state.messageFeedback.get(messageId) ?? emptyFeedbackList,
    );
    const currentUserFeedback = useMemo(
        () => feedbackList.find((item) => item.is_current_user),
        [feedbackList],
    );
    const otherFeedbacks = useMemo(
        () => feedbackList.filter((item) => !item.is_current_user),
        [feedbackList],
    );
    const allFeedbacks = useMemo(
        () => [
            ...(currentUserFeedback ? [currentUserFeedback] : []),
            ...otherFeedbacks,
        ],
        [currentUserFeedback, otherFeedbacks],
    );

    if (!isEligible || allFeedbacks.length === 0) {
        return undefined;
    }

    return (
        <ul className="border-border/70 bg-muted/30 w-full max-w-xl space-y-3 rounded-lg border px-3 py-2.5">
            {allFeedbacks.map((item) => (
                <li
                    className="flex items-start gap-2 text-sm"
                    key={item.id}
                >
                    {item.rating === "thumbs_up" ? (
                        <ThumbsUp className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    ) : (
                        <ThumbsDown className="text-destructive mt-0.5 size-4 shrink-0" />
                    )}
                    <div className="min-w-0 flex-1 space-y-0.5">
                        <div className="text-foreground font-medium">
                            {item.user_name}
                        </div>
                        {item.text !== undefined && item.text.trim() !== "" ? (
                            <p className="text-muted-foreground break-words whitespace-pre-wrap">
                                {item.text}
                            </p>
                        ) : (
                            <p className="text-muted-foreground italic">
                                No comment
                            </p>
                        )}
                    </div>
                </li>
            ))}
        </ul>
    );
};

export const MessageFeedback = ({
    messageId,
    isEligible = true,
    feedbackSource = "chat",
    hideOtherFeedbacksPopover = false,
    onFeedbackChange,
}: MessageFeedbackProps): JSX.Element | undefined => {
    const feedbackList = useChatStore(
        (state) => state.messageFeedback.get(messageId) ?? emptyFeedbackList,
    );
    const isLoaded = useChatStore((state) =>
        state.messageFeedback.has(messageId),
    );
    const isLoading = useChatStore((state) =>
        state.messageFeedbackLoading.has(messageId),
    );

    const {
        loadMessageFeedback,
        submitMessageFeedback,
        removeMessageFeedback,
    } = useChatActions();

    const [dialogOpen, setDialogOpen] = useState(false);
    const [feedbackText, setFeedbackText] = useState("");

    useEffect(() => {
        if (!isEligible) {
            return;
        }
        if (!isLoaded) {
            void loadMessageFeedback(messageId, feedbackSource);
        }
    }, [feedbackSource, isEligible, isLoaded, loadMessageFeedback, messageId]);

    const currentUserFeedback = useMemo(
        () => feedbackList.find((item) => item.is_current_user),
        [feedbackList],
    );

    const otherFeedbacks = useMemo(
        () => feedbackList.filter((item) => !item.is_current_user),
        [feedbackList],
    );

    const currentRating = currentUserFeedback?.rating;

    const hasFeedbackText =
        currentUserFeedback?.text !== undefined &&
        currentUserFeedback.text.trim() !== "";

    const positiveTooltip = useMemo(() => {
        if (currentRating === "thumbs_up") {
            return "Edit or remove feedback";
        }
        return "Good response";
    }, [currentRating]);

    const negativeTooltip = useMemo(() => {
        if (currentRating === "thumbs_down") {
            return "Edit or remove feedback";
        }
        return "Poor response";
    }, [currentRating]);

    const handleFeedbackClick = async (rating: Rating): Promise<void> => {
        if (!isEligible) {
            return;
        }

        if (currentUserFeedback?.rating === rating) {
            setFeedbackText(currentUserFeedback.text ?? "");
            setDialogOpen(true);
            return;
        }

        await submitMessageFeedback(
            messageId,
            rating,
            currentUserFeedback?.text ?? undefined,
            feedbackSource,
        );
        onFeedbackChange?.({
            previous: currentUserFeedback?.rating,
            next: rating,
        });
    };

    const handleSave = (): void => {
        if (!currentUserFeedback) {
            return;
        }
        void submitMessageFeedback(
            messageId,
            currentUserFeedback.rating,
            feedbackText,
            feedbackSource,
        );
        setDialogOpen(false);
    };

    const handleRemove = async (): Promise<void> => {
        if (!currentUserFeedback) {
            return;
        }
        await removeMessageFeedback(messageId, feedbackSource);
        onFeedbackChange?.({
            previous: currentUserFeedback.rating,
            next: undefined,
        });
        setDialogOpen(false);
    };

    if (!isEligible) {
        return undefined;
    }

    return (
        <>
            <div className="flex flex-col items-start gap-2">
                <div className="flex items-center gap-1">
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    aria-label="Thumbs up"
                                    className={
                                        currentRating === "thumbs_up"
                                            ? "rounded-full bg-emerald-500/10 text-emerald-600 transition hover:bg-emerald-500/15 hover:text-emerald-600 dark:text-emerald-400 dark:hover:text-emerald-400"
                                            : "text-muted-foreground rounded-full transition"
                                    }
                                    disabled={isLoading}
                                    onClick={() => {
                                        void handleFeedbackClick("thumbs_up");
                                    }}
                                    size="icon-sm"
                                    type="button"
                                    variant="ghost"
                                >
                                    <ThumbsUp
                                        aria-hidden="true"
                                        className="size-4"
                                    />
                                </Button>
                            }
                        />
                        <TooltipContent>{positiveTooltip}</TooltipContent>
                    </Tooltip>

                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    aria-label="Thumbs down"
                                    className={
                                        currentRating === "thumbs_down"
                                            ? "bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive rounded-full transition"
                                            : "text-muted-foreground rounded-full transition"
                                    }
                                    disabled={isLoading}
                                    onClick={() => {
                                        void handleFeedbackClick("thumbs_down");
                                    }}
                                    size="icon-sm"
                                    type="button"
                                    variant="ghost"
                                >
                                    <ThumbsDown
                                        aria-hidden="true"
                                        className="size-4"
                                    />
                                </Button>
                            }
                        />
                        <TooltipContent>{negativeTooltip}</TooltipContent>
                    </Tooltip>

                    {currentUserFeedback && (
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        aria-label="Feedback comment"
                                        className={
                                            hasFeedbackText
                                                ? "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary rounded-full transition"
                                                : "text-muted-foreground rounded-full transition"
                                        }
                                        disabled={isLoading}
                                        onClick={() => {
                                            setFeedbackText(
                                                currentUserFeedback.text ?? "",
                                            );
                                            setDialogOpen(true);
                                        }}
                                        size="icon-sm"
                                        type="button"
                                        variant="ghost"
                                    >
                                        <MessageSquareText
                                            aria-hidden="true"
                                            className="size-4"
                                        />
                                    </Button>
                                }
                            />
                            <TooltipContent>
                                {hasFeedbackText
                                    ? currentUserFeedback.text
                                    : "Add feedback comment"}
                            </TooltipContent>
                        </Tooltip>
                    )}

                    {otherFeedbacks.length > 0 &&
                        !hideOtherFeedbacksPopover && (
                            <OtherFeedbacksPopover feedbacks={otherFeedbacks} />
                        )}
                </div>
            </div>

            <Dialog
                disablePointerDismissal
                onOpenChange={(open) => {
                    setDialogOpen(open);
                }}
                open={dialogOpen}
            >
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Feedback comment</DialogTitle>
                    </DialogHeader>

                    <Textarea
                        disabled={!currentUserFeedback}
                        onChange={(event) => {
                            setFeedbackText(event.target.value);
                        }}
                        placeholder="Additional feedback (optional)"
                        rows={4}
                        value={feedbackText}
                    />

                    <DialogFooter>
                        <Button
                            disabled={!currentUserFeedback || isLoading}
                            onClick={() => {
                                void handleRemove();
                            }}
                            type="button"
                            variant="destructive"
                        >
                            Remove feedback
                        </Button>
                        <Button
                            onClick={() => {
                                setDialogOpen(false);
                            }}
                            type="button"
                            variant="outline"
                        >
                            Cancel
                        </Button>
                        <Button
                            disabled={!currentUserFeedback || isLoading}
                            onClick={handleSave}
                            type="button"
                        >
                            Save
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
};
