import { Button } from "@va/shared/components/ui/button";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { cn } from "@va/shared/lib/utils";
import { Square, Volume2 } from "lucide-react";
import type { JSX } from "react";

interface TTSButtonProps {
    isPlaying: boolean;
    onClick: () => void;
}

export const TTSButton = ({
    isPlaying,
    onClick,
}: TTSButtonProps): JSX.Element => {
    const Icon = isPlaying ? Square : Volume2;
    const tooltipText = isPlaying ? "Stop" : "Read aloud";

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        aria-label={tooltipText}
                        className={cn(
                            "text-muted-foreground rounded-full transition",
                            isPlaying &&
                                "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary",
                        )}
                        onClick={onClick}
                        size="icon-sm"
                        type="button"
                        variant="ghost"
                    >
                        <Icon
                            aria-hidden="true"
                            className="size-4"
                        />
                    </Button>
                }
            />
            <TooltipContent>{tooltipText}</TooltipContent>
        </Tooltip>
    );
};
