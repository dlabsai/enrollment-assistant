import { Button } from "@va/shared/components/ui/button";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "@va/shared/components/ui/sheet";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { cn } from "@va/shared/lib/utils";
import { ExternalLink, Maximize2, Minimize2, RefreshCw } from "lucide-react";
import type { JSX } from "react";

import { TraceSheetResizeHandle } from "../../traces/components/trace-sheet-resize-handle";
import { TraceTurnDebugView } from "../../traces/components/trace-turn-debug-view";
import { useTraceDetailByMessage } from "../../traces/hooks/use-trace-detail-by-message";
import { useTraceSheetPanel } from "../../traces/hooks/use-trace-sheet-panel";
import { TRACE_SHEET_WIDTH_CLASS } from "../../traces/lib/trace-layout";

interface ChatTurnTraceSheetProps {
    messageId: string | undefined;
    onOpenChange: (open: boolean) => void;
    open: boolean;
    source?: "chat_trace" | "chats_trace";
}

const openUrl = (url: string): void => {
    window.open(url, "_blank", "noopener,noreferrer");
};

export const ChatTurnTraceSheet = ({
    messageId,
    onOpenChange,
    open,
    source = "chats_trace",
}: ChatTurnTraceSheetProps): JSX.Element => {
    const traceSheetPanel = useTraceSheetPanel();
    const { detail, loading, error, refresh } = useTraceDetailByMessage(
        messageId,
        source,
    );
    const hasMessageId = messageId !== undefined && messageId.trim() !== "";

    const handleOpenChange = (nextOpen: boolean): void => {
        if (!nextOpen) {
            traceSheetPanel.handleCancelResize();
        }
        onOpenChange(nextOpen);
    };

    const openTraceInNewTab = (): void => {
        if (detail?.trace_id === undefined || detail.trace_id === "") {
            return;
        }
        const base = `${window.location.origin}${window.location.pathname}`;
        openUrl(`${base}#/traces/${detail.trace_id}?view=summary`);
    };

    return (
        <Sheet
            onOpenChange={handleOpenChange}
            open={open}
        >
            <SheetContent
                className={cn(
                    "flex flex-col gap-4 p-0",
                    TRACE_SHEET_WIDTH_CLASS,
                    traceSheetPanel.isResizing &&
                        "select-none !transition-none",
                )}
                initialFocus={false}
                style={traceSheetPanel.panelStyle}
            >
                <SheetHeader className="border-b px-4 py-4">
                    <div className="flex items-start justify-between gap-4">
                        <div className="space-y-1">
                            <SheetTitle>Chat Turn Trace</SheetTitle>
                            <SheetDescription>
                                {hasMessageId
                                    ? `Message ${messageId}`
                                    : "Trace detail"}
                            </SheetDescription>
                        </div>
                        <TooltipProvider>
                            <div className="mr-8 flex items-center gap-2">
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                aria-label={
                                                    traceSheetPanel.isExpanded
                                                        ? "Collapse trace sheet"
                                                        : "Expand trace sheet"
                                                }
                                                onClick={
                                                    traceSheetPanel.handleToggleExpanded
                                                }
                                                size="icon-sm"
                                                type="button"
                                                variant="outline"
                                            >
                                                {traceSheetPanel.isExpanded ? (
                                                    <Minimize2 className="size-4" />
                                                ) : (
                                                    <Maximize2 className="size-4" />
                                                )}
                                            </Button>
                                        }
                                    />
                                    <TooltipContent>
                                        {traceSheetPanel.isExpanded
                                            ? "Collapse sheet"
                                            : "Expand to full viewport"}
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                aria-label="Open trace in new tab"
                                                disabled={
                                                    detail?.trace_id ===
                                                        undefined ||
                                                    detail.trace_id === ""
                                                }
                                                onClick={openTraceInNewTab}
                                                size="icon-sm"
                                                type="button"
                                                variant="outline"
                                            >
                                                <ExternalLink className="size-4" />
                                            </Button>
                                        }
                                    />
                                    <TooltipContent>
                                        Open in new tab
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                aria-label="Refresh trace"
                                                onClick={refresh}
                                                size="icon-sm"
                                                type="button"
                                                variant="outline"
                                            >
                                                <RefreshCw className="size-4" />
                                            </Button>
                                        }
                                    />
                                    <TooltipContent>
                                        Refresh trace
                                    </TooltipContent>
                                </Tooltip>
                            </div>
                        </TooltipProvider>
                    </div>
                </SheetHeader>
                <div className="min-h-0 flex-1 overflow-hidden">
                    <TraceTurnDebugView
                        detail={detail}
                        error={error}
                        key={detail?.trace_id}
                        layoutScope="peek"
                        loading={loading}
                    />
                </div>
                <TraceSheetResizeHandle
                    isResizing={traceSheetPanel.isResizing}
                    resizeHandleProps={traceSheetPanel.resizeHandleProps}
                />
            </SheetContent>
        </Sheet>
    );
};
