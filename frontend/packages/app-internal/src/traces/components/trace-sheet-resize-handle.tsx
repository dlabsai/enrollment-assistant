import { cn } from "@va/shared/lib/utils";
import type { ComponentProps, JSX } from "react";

interface TraceSheetResizeHandleProps {
    isResizing: boolean;
    resizeHandleProps: ComponentProps<"div">;
}

export const TraceSheetResizeHandle = ({
    isResizing,
    resizeHandleProps,
}: TraceSheetResizeHandleProps): JSX.Element => (
    <div
        {...resizeHandleProps}
        className="group/resize absolute inset-y-0 -left-1 hidden w-3 cursor-ew-resize touch-none justify-center focus-visible:outline-hidden md:flex"
        title="Resize trace sheet"
    >
        <div
            aria-hidden
            className={cn(
                "h-full w-1 rounded-full transition-colors",
                "group-hover/resize:bg-muted-foreground/40 group-focus-visible/resize:bg-muted-foreground/50",
                isResizing
                    ? "bg-muted-foreground/60"
                    : "bg-transparent",
            )}
        />
    </div>
);
