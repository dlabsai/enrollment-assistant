import { Button } from "@va/shared/components/ui/button";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { useIsMobile } from "@va/shared/hooks/use-is-mobile";
import { cn } from "@va/shared/lib/utils";
import { GraduationCap, RotateCcw, X } from "lucide-react";
import type { JSX } from "react";

interface HeaderProps {
    onClose: () => void;
    onReset: () => void;
}

export const Header = ({ onClose, onReset }: HeaderProps): JSX.Element => {
    const isMobile = useIsMobile(480);

    const containerClasses = cn(
        "flex items-center justify-between gap-1.5 px-4 py-2.5",
        isMobile ? "px-4 py-2.5" : "px-4 py-2.5",
    );

    return (
        <header className={containerClasses}>
            <div className="flex items-center gap-1.5">
                <GraduationCap
                    aria-hidden="true"
                    className="text-foreground size-[19px]"
                />
                <p className="font-header text-foreground font-semibold tracking-wide">
                    Enrollment Assistant
                </p>
            </div>
            <div className="flex items-center gap-1.5">
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                aria-label="Clear chat history"
                                className="group rounded-full"
                                onClick={onReset}
                                size="icon"
                                variant="ghost"
                            >
                                <RotateCcw
                                    aria-hidden="true"
                                    className="text-foreground size-[19px]"
                                />
                            </Button>
                        }
                    />
                    <TooltipContent sideOffset={4}>
                        <p>Clear</p>
                    </TooltipContent>
                </Tooltip>

                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                aria-label="Close widget"
                                className="group rounded-full"
                                onClick={onClose}
                                size="icon"
                                variant="ghost"
                            >
                                <X
                                    aria-hidden="true"
                                    className="text-foreground size-[19px]"
                                />
                            </Button>
                        }
                    />
                    <TooltipContent sideOffset={4}>
                        <p>Close</p>
                    </TooltipContent>
                </Tooltip>
            </div>
        </header>
    );
};
