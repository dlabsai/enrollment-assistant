import { Streamdown } from "@va/shared/components/streamdown";
import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@va/shared/components/ui/dialog";
import { Toggle } from "@va/shared/components/ui/toggle";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { cn } from "@va/shared/lib/utils";
import { ShieldAlert } from "lucide-react";
import { type JSX,useState } from "react";

import type { Message, MessageGuardrailsFailure } from "../types";

const guardrailsFailureKey = (failure: MessageGuardrailsFailure): string =>
    `${failure.assistantMessage}\u0000${failure.llmGuardrailsFeedback ?? ""}\u0000${(failure.invalidUrls ?? []).join("\u0000")}`;

const GuardrailsTextContent = ({
    formatted,
    text,
}: {
    formatted: boolean;
    text: string;
}): JSX.Element => {
    if (formatted) {
        return <Streamdown className="max-w-none break-words text-xs">{text}</Streamdown>;
    }
    return <div className="text-xs break-words whitespace-pre-wrap">{text}</div>;
};

const GuardrailsFailureCard = ({
    failure,
    formatted,
    index,
}: {
    failure: MessageGuardrailsFailure;
    formatted: boolean;
    index: number;
}): JSX.Element => {
    const feedback = failure.llmGuardrailsFeedback;
    const invalidUrls = failure.invalidUrls ?? [];

    return (
        <div className="space-y-3 rounded-lg border p-3">
            <div className="text-sm font-medium">Failed attempt {index + 1}</div>
            {feedback === undefined || feedback.trim() === "" ? undefined : (
                <div className="space-y-1">
                    <div className="text-muted-foreground text-xs font-medium">
                        LLM guardrails feedback
                    </div>
                    <div className="bg-muted/60 rounded-md p-2">
                        <GuardrailsTextContent formatted={formatted} text={feedback} />
                    </div>
                </div>
            )}
            {invalidUrls.length > 0 ? (
                <div className="space-y-1">
                    <div className="text-muted-foreground text-xs font-medium">
                        Invalid URLs
                    </div>
                    <ul className="bg-muted/60 list-disc rounded-md py-2 pr-2 pl-5 text-xs break-all">
                        {invalidUrls.map((url) => (
                            <li key={url}>{url}</li>
                        ))}
                    </ul>
                </div>
            ) : undefined}
            <div className="space-y-1">
                <div className="text-muted-foreground text-xs font-medium">
                    Response that failed
                </div>
                <div className="bg-muted/60 rounded-md p-2">
                    <GuardrailsTextContent
                        formatted={formatted}
                        text={failure.assistantMessage}
                    />
                </div>
            </div>
        </div>
    );
};

export const GuardrailsFooter = ({
    message,
}: {
    message: Message | undefined;
}): JSX.Element | undefined => {
    const [formatted, setFormatted] = useState(true);

    if (
        message?.role !== "assistant" ||
        message.guardrailsFailures === undefined ||
        message.guardrailsFailures.length === 0
    ) {
        return undefined;
    }

    const blocked = message.guardrailsBlocked === true;
    const attemptLabel =
        message.guardrailsFailures.length === 1
            ? "1 failed guardrails attempt"
            : `${message.guardrailsFailures.length} failed guardrails attempts`;

    return (
        <Dialog>
            <TooltipProvider delay={0}>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <DialogTrigger
                                render={
                                    <Button
                                        aria-label="Show guardrails failures"
                                        className={cn(
                                            "rounded-full",
                                            blocked && "text-destructive hover:text-destructive",
                                        )}
                                        size="icon-sm"
                                        type="button"
                                        variant="ghost"
                                    >
                                        <ShieldAlert className="size-4" />
                                    </Button>
                                }
                            />
                        }
                    />
                    <TooltipContent>{attemptLabel}</TooltipContent>
                </Tooltip>
            </TooltipProvider>
            <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
                <DialogHeader>
                    <DialogTitle>Guardrails failures</DialogTitle>
                </DialogHeader>
                <div className="flex items-start justify-between gap-3">
                    <div className="text-muted-foreground text-sm">
                        {blocked
                            ? "This response was blocked after guardrails retries."
                            : "This response was revised after guardrails feedback."}
                    </div>
                    <Toggle
                        onPressedChange={setFormatted}
                        pressed={formatted}
                        size="sm"
                        variant="outline"
                    >
                        {formatted ? "Formatted" : "Plain"}
                    </Toggle>
                </div>
                <div className="space-y-3 pr-1">
                    {message.guardrailsFailures.map((failure, index) => (
                        <GuardrailsFailureCard
                            failure={failure}
                            formatted={formatted}
                            index={index}
                            key={guardrailsFailureKey(failure)}
                        />
                    ))}
                </div>
            </DialogContent>
        </Dialog>
    );
};
