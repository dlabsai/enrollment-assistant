import { splitHighlightText } from "@va/shared/lib/highlight";
import { cn } from "@va/shared/lib/utils";
import type { JSX } from "react";

const DEFAULT_HIGHLIGHT_CLASS =
    "bg-amber-200/70 text-foreground dark:bg-amber-500/40 rounded-sm px-0.5";

interface HighlightedTextProps {
    text: string;
    query: string;
    className?: string;
    highlightClassName?: string;
    phrase?: boolean;
}

export const HighlightedText = ({
    text,
    query,
    className,
    highlightClassName,
    phrase = false,
}: HighlightedTextProps): JSX.Element => {
    if (query.trim() === "") {
        return <span className={className}>{text}</span>;
    }

    const parts = splitHighlightText(text, query, phrase);

    return (
        <span className={className}>
            {parts.map((part) =>
                part.highlight ? (
                    <mark
                        className={cn(
                            DEFAULT_HIGHLIGHT_CLASS,
                            highlightClassName,
                        )}
                        key={`${part.text}-${part.start}`}
                    >
                        {part.text}
                    </mark>
                ) : (
                    <span key={`${part.text}-${part.start}`}>{part.text}</span>
                ),
            )}
        </span>
    );
};

export { DEFAULT_HIGHLIGHT_CLASS };
