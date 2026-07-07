import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { CircleDollarSign } from "lucide-react";
import type { JSX } from "react";

import {
    formatEstimatedUsdCost,
    formatLocaleNumber,
} from "../../lib/number-format";
import type { Message } from "../types";

const formatTokenCount = (value: number | undefined): string =>
    value === undefined ? "-" : formatLocaleNumber(value);

const responseCostRows = (message: Message): { label: string; value: string }[] => [
    {
        label: "Uncached input",
        value: `${formatTokenCount(message.responseUsage?.uncachedInputTokens)} · ${formatEstimatedUsdCost(message.responseCostBreakdown?.inputCost)}`,
    },
    {
        label: "Cached input",
        value: `${formatTokenCount(message.responseUsage?.cacheReadInputTokens)} · ${formatEstimatedUsdCost(message.responseCostBreakdown?.cacheReadInputCost)}`,
    },
    {
        label: "Output",
        value: `${formatTokenCount(message.responseUsage?.outputTokens)} · ${formatEstimatedUsdCost(message.responseCostBreakdown?.outputCost)}`,
    },
];

export const renderResponseCostFooter = (
    message: Message | undefined,
    canShowCost: boolean,
): JSX.Element | undefined => {
    if (
        !canShowCost ||
        message?.role !== "assistant" ||
        message.responseCost === undefined
    ) {
        return undefined;
    }

    const content = (
        <span className="inline-flex items-center gap-1">
            <CircleDollarSign className="size-3" />
            {formatEstimatedUsdCost(message.responseCost)}
        </span>
    );

    return message.responseUsage === undefined &&
        message.responseCostBreakdown === undefined ? (
        content
    ) : (
        <TooltipProvider delay={0}>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <span className="inline-flex cursor-help items-center">
                            {content}
                        </span>
                    }
                />
                <TooltipContent side="top">
                    <div className="space-y-1 text-xs">
                        {responseCostRows(message).map((row) => (
                            <div key={row.label}>
                                {row.label}: {row.value}
                            </div>
                        ))}
                    </div>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};
