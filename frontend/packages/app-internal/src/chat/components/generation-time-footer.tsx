import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { Clock3 } from "lucide-react";
import type { JSX } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import type { Message } from "../types";

interface TooltipLine {
    id: string;
    text: string;
}

const formatGenerationTime = (durationMs: number): string => {
    if (!Number.isFinite(durationMs) || durationMs <= 0) {
        return "-";
    }
    if (durationMs < 1000) {
        return `${formatLocaleNumber(Math.round(durationMs))}ms`;
    }
    return `${formatLocaleNumber(durationMs / 1000, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}s`;
};

const sumAttemptTimes = (values: number[] | undefined): number | undefined => {
    if (values === undefined || values.length === 0) {
        return undefined;
    }
    return values.reduce((sum, value) => sum + value, 0);
};

const getGenerationTimingTooltipLines = (message: Message): TooltipLine[] => {
    const timing = message.generationTiming;
    if (timing === undefined) {
        return [];
    }

    const {
        chatbotModel,
        chatbotTimeMs: rawChatbotTimeMs,
        chatbotTimesMs,
        guardrailModel,
        guardrailTimeMs,
        guardrailTimesMs,
        totalTimeMs: rawTotalTimeMs,
    } = timing;
    const lines: TooltipLine[] = [];
    const totalTimeMs = rawTotalTimeMs ?? message.generationTimeMs;
    if (totalTimeMs !== undefined && totalTimeMs > 0) {
        lines.push({
            id: "total",
            text: `Total: ${formatGenerationTime(totalTimeMs)}`,
        });
    }
    const chatbotTimeMs = sumAttemptTimes(chatbotTimesMs) ?? rawChatbotTimeMs;
    if (chatbotTimeMs !== undefined && chatbotTimeMs > 0) {
        lines.push({
            id: "chatbot",
            text: `Chatbot: ${formatGenerationTime(chatbotTimeMs)} (${chatbotModel ?? "unknown"})`,
        });
        if (chatbotTimesMs !== undefined && chatbotTimesMs.length > 1) {
            for (const [index, attemptMs] of chatbotTimesMs.entries()) {
                lines.push({
                    id: `chatbot-attempt-${index + 1}`,
                    text: `• Attempt ${formatLocaleNumber(index + 1)}: ${formatGenerationTime(attemptMs)}`,
                });
            }
        }
    }
    if (guardrailTimeMs !== undefined && guardrailTimeMs > 0) {
        lines.push({
            id: "guardrails",
            text: `Guardrails: ${formatGenerationTime(guardrailTimeMs)} (${guardrailModel ?? "unknown"})`,
        });
        if (guardrailTimesMs !== undefined && guardrailTimesMs.length > 1) {
            for (const [index, attemptMs] of guardrailTimesMs.entries()) {
                const status =
                    index < guardrailTimesMs.length - 1 ? "failed" : "passed";
                lines.push({
                    id: `guardrails-attempt-${index + 1}`,
                    text: `• Attempt ${formatLocaleNumber(index + 1)}: ${formatGenerationTime(attemptMs)} (${status})`,
                });
            }
        }
    }

    return lines;
};

export const renderGenerationTimeFooter = (
    message: Message | undefined,
    canShowTooltip: boolean,
): JSX.Element | undefined => {
    if (
        message?.role !== "assistant" ||
        message.generationTimeMs === undefined
    ) {
        return undefined;
    }

    const content = (
        <span className="inline-flex items-center gap-1">
            <Clock3 className="size-3" />
            {formatGenerationTime(message.generationTimeMs)}
        </span>
    );
    const tooltipLines = getGenerationTimingTooltipLines(message);

    return !canShowTooltip || tooltipLines.length === 0 ? (
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
                        {tooltipLines.map((line) => (
                            <div key={line.id}>{line.text}</div>
                        ))}
                    </div>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};
