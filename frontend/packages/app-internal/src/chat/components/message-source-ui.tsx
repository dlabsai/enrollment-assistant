import { SourceLinks } from "@va/shared/components/source-links";
import { Button } from "@va/shared/components/ui/button";
import { Spinner } from "@va/shared/components/ui/spinner";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { BookOpen, Wrench } from "lucide-react";
import type { JSX } from "react";

import type {
    MessageSourcePanelMessage,
    MessageSourcePanelState,
} from "./message-source-state";

const EMPTY_GROUNDING_MESSAGE = "No specific sources were identified for this answer.";

const canShowSourcesButton = (
    message: MessageSourcePanelMessage,
    canViewSources: boolean,
): boolean =>
    canViewSources &&
    message.role === "assistant" &&
    message.groundingSourceStatus !== undefined &&
    message.groundingSourceStatus !== null;

const canShowToolsButton = (
    message: MessageSourcePanelMessage,
    canViewTools: boolean,
): boolean =>
    canViewTools &&
    message.role === "assistant" &&
    (message.toolSourcesUsed?.length ?? 0) > 0;

const isGroundingPending = (message: MessageSourcePanelMessage): boolean =>
    message.groundingSourceStatus === "pending";

const canOpenSourcesPanel = (
    message: MessageSourcePanelMessage,
    canViewSources: boolean,
): boolean => canShowSourcesButton(message, canViewSources) && !isGroundingPending(message);

const hasOpenMessageSourcePanels = (
    message: MessageSourcePanelMessage,
    state: MessageSourcePanelState,
    options: {
        canViewSources: boolean;
        canViewTools: boolean;
    },
): boolean =>
    (canOpenSourcesPanel(message, options.canViewSources) &&
        state.sourcesOpenMessageIds.has(message.id)) ||
    (canShowToolsButton(message, options.canViewTools) &&
        state.toolSourcesOpenMessageIds.has(message.id));

interface MessageSourceButtonsProps {
    canViewSources: boolean;
    canViewTools: boolean;
    disabled?: boolean;
    message: MessageSourcePanelMessage;
    state: MessageSourcePanelState;
}

export const MessageSourceButtons = ({
    canViewSources,
    canViewTools,
    disabled = false,
    message,
    state,
}: MessageSourceButtonsProps): JSX.Element | null => {
    const sourceCount = message.groundingSourcesUsed?.length ?? 0;
    const sourcesOpen = state.sourcesOpenMessageIds.has(message.id);
    const sourcesPending = isGroundingPending(message);
    const sourcesLabel = sourcesPending
        ? "Checking sources"
        : sourcesOpen
          ? "Hide sources"
          : "Show sources";
    const sourcesTooltip = sourcesPending
        ? "Checking sources"
        : sourcesOpen
          ? "Hide sources"
          : sourceCount > 0
            ? `Show ${sourceCount} ${sourceCount === 1 ? "source" : "sources"}`
            : "Show sources";
    const toolsOpen = state.toolSourcesOpenMessageIds.has(message.id);

    const sourcesButton = canShowSourcesButton(message, canViewSources) ? (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        aria-label={sourcesLabel}
                        className="text-muted-foreground rounded-full transition"
                        disabled={disabled || sourcesPending}
                        onClick={() => {
                            state.toggleSourcesPanel(message.id);
                        }}
                        size="icon-sm"
                        type="button"
                        variant={sourcesOpen && !sourcesPending ? "secondary" : "ghost"}
                    >
                        {sourcesPending ? (
                            <Spinner className="size-4" />
                        ) : (
                            <BookOpen className="size-4" />
                        )}
                        <span className="sr-only">{sourcesLabel}</span>
                    </Button>
                }
            />
            <TooltipContent>{sourcesTooltip}</TooltipContent>
        </Tooltip>
    ) : undefined;

    const toolsButton = canShowToolsButton(message, canViewTools) ? (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        aria-label={toolsOpen ? "Hide tools" : "Show tools"}
                        className="text-muted-foreground rounded-full transition"
                        disabled={disabled}
                        onClick={() => {
                            state.toggleToolSourcesPanel(message.id);
                        }}
                        size="icon-sm"
                        type="button"
                        variant={toolsOpen ? "secondary" : "ghost"}
                    >
                        <Wrench className="size-4" />
                        <span className="sr-only">
                            {toolsOpen ? "Hide tools" : "Show tools"}
                        </span>
                    </Button>
                }
            />
            <TooltipContent>{toolsOpen ? "Hide tools" : "Show tools"}</TooltipContent>
        </Tooltip>
    ) : undefined;

    if (sourcesButton === undefined && toolsButton === undefined) {
        return null;
    }

    return (
        <TooltipProvider delay={0}>
            {sourcesButton}
            {toolsButton}
        </TooltipProvider>
    );
};

interface MessageSourcePanelsProps {
    canViewSources: boolean;
    canViewTools: boolean;
    message: MessageSourcePanelMessage;
    state: MessageSourcePanelState;
}

export const MessageSourcePanels = ({
    canViewSources,
    canViewTools,
    message,
    state,
}: MessageSourcePanelsProps): JSX.Element | null => {
    if (
        !hasOpenMessageSourcePanels(message, state, {
            canViewSources,
            canViewTools,
        })
    ) {
        return null;
    }

    return (
        <div className="space-y-2">
            {canOpenSourcesPanel(message, canViewSources) &&
            state.sourcesOpenMessageIds.has(message.id) ? (
                <SourceLinks
                    emptyMessage={EMPTY_GROUNDING_MESSAGE}
                    grouped={false}
                    sources={message.groundingSourcesUsed}
                />
            ) : undefined}
            {canShowToolsButton(message, canViewTools) &&
            state.toolSourcesOpenMessageIds.has(message.id) ? (
                <SourceLinks sources={message.toolSourcesUsed} />
            ) : undefined}
        </div>
    );
};
