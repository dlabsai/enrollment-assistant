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
import { type JSX, useState } from "react";

import { TraceTurnDebugView } from "../../traces/components/trace-turn-debug-view";
import { useTraceDetailByMessage } from "../../traces/hooks/use-trace-detail-by-message";

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
    const [expanded, setExpanded] = useState(false);
    const { detail, loading, error, refresh } = useTraceDetailByMessage(
        messageId,
        source,
    );
    const hasMessageId = messageId !== undefined && messageId.trim() !== "";

    const openTraceInNewTab = (): void => {
        if (detail?.trace_id === undefined || detail.trace_id === "") {
            return;
        }
        const base = `${window.location.origin}${window.location.pathname}`;
        openUrl(`${base}#/traces/${detail.trace_id}?view=summary`);
    };

    return (
        <Sheet
            onOpenChange={onOpenChange}
            open={open}
        >
            <SheetContent
                className={cn(
                    "flex flex-col gap-4 p-0",
                    expanded
                        ? "!w-screen !max-w-none"
                        : "!w-[min(100vw,1200px)] !max-w-[min(100vw,1200px)]",
                )}
                initialFocus={false}
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
                                                    expanded
                                                        ? "Collapse trace sheet"
                                                        : "Expand trace sheet"
                                                }
                                                onClick={() => {
                                                    setExpanded(
                                                        (value) => !value,
                                                    );
                                                }}
                                                size="icon-sm"
                                                type="button"
                                                variant="outline"
                                            >
                                                {expanded ? (
                                                    <Minimize2 className="size-4" />
                                                ) : (
                                                    <Maximize2 className="size-4" />
                                                )}
                                            </Button>
                                        }
                                    />
                                    <TooltipContent>
                                        {expanded
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
                                                onClick={() => {
                                                    void refresh();
                                                }}
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
                        loading={loading}
                        summaryOnly
                    />
                </div>
            </SheetContent>
        </Sheet>
    );
};
