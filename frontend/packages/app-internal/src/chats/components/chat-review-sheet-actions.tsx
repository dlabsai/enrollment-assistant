import { Button } from "@va/shared/components/ui/button";
import { Label } from "@va/shared/components/ui/label";
import { Switch } from "@va/shared/components/ui/switch";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { ChevronLeft, ChevronRight, Copy, ExternalLink } from "lucide-react";
import type { JSX } from "react";

interface ChatReviewSheetActionsProps {
    canGoNext: boolean;
    canGoPrev: boolean;
    copyDisabled: boolean;
    nextLabel: string;
    onCopyTranscript: () => void;
    onGoNext: () => void;
    onGoPrev: () => void;
    onOpenChat: () => void;
    onShowSummaryChange: (show: boolean) => void;
    openChatDisabled?: boolean;
    openChatTooltip?: string;
    previousLabel: string;
    showSummary: boolean;
    summaryToggleId: string;
}

export const ChatReviewSheetActions = ({
    canGoNext,
    canGoPrev,
    copyDisabled,
    nextLabel,
    onCopyTranscript,
    onGoNext,
    onGoPrev,
    onOpenChat,
    onShowSummaryChange,
    openChatDisabled = false,
    openChatTooltip = "Open in new tab",
    previousLabel,
    showSummary,
    summaryToggleId,
}: ChatReviewSheetActionsProps): JSX.Element => (
    <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
            <Label
                className="text-muted-foreground text-xs"
                htmlFor={summaryToggleId}
            >
                Summary
            </Label>
            <Switch
                checked={showSummary}
                id={summaryToggleId}
                onCheckedChange={onShowSummaryChange}
            />
        </div>
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            aria-label="Copy transcript"
                            disabled={copyDisabled}
                            onClick={onCopyTranscript}
                            size="icon-sm"
                            type="button"
                            variant="ghost"
                        >
                            <Copy className="size-4" />
                        </Button>
                    }
                />
                <TooltipContent>Copy transcript</TooltipContent>
            </Tooltip>
        </TooltipProvider>
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            aria-label="Open chat in new tab"
                            disabled={openChatDisabled}
                            onClick={onOpenChat}
                            size="icon-sm"
                            type="button"
                            variant="ghost"
                        >
                            <ExternalLink className="size-4" />
                        </Button>
                    }
                />
                <TooltipContent>{openChatTooltip}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
        <TooltipProvider>
            <div className="mr-8 flex items-center gap-2">
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                aria-label={previousLabel}
                                disabled={!canGoPrev}
                                onClick={onGoPrev}
                                size="icon-sm"
                                variant="outline"
                            >
                                <ChevronLeft className="size-4" />
                            </Button>
                        }
                    />
                    <TooltipContent>{previousLabel}</TooltipContent>
                </Tooltip>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                aria-label={nextLabel}
                                disabled={!canGoNext}
                                onClick={onGoNext}
                                size="icon-sm"
                                variant="outline"
                            >
                                <ChevronRight className="size-4" />
                            </Button>
                        }
                    />
                    <TooltipContent>{nextLabel}</TooltipContent>
                </Tooltip>
            </div>
        </TooltipProvider>
    </div>
);
