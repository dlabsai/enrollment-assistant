"use client";

import * as React from "react";
import { ScrollArea as ScrollAreaPrimitive } from "@base-ui/react/scroll-area";

import { cn } from "@va/shared/lib/utils";

type ScrollAreaProps = ScrollAreaPrimitive.Root.Props & {
    overflowFadeClassName?: string;
    scrollbarAlwaysVisible?: boolean;
    scrollbarClassName?: string;
    viewportClassName?: string;
    viewportProps?: Omit<
        ScrollAreaPrimitive.Viewport.Props,
        "children" | "className" | "ref" | "render"
    >;
    viewportRef?: React.Ref<HTMLDivElement>;
    viewportRender?: React.ReactElement;
};

function ScrollArea({
    className,
    children,
    overflowFadeClassName,
    scrollbarAlwaysVisible,
    scrollbarClassName,
    viewportClassName,
    viewportProps,
    viewportRef,
    viewportRender,
    ...props
}: ScrollAreaProps) {
    return (
        <ScrollAreaPrimitive.Root
            data-slot="scroll-area"
            className={cn("group/scroll-area relative", className)}
            {...props}
        >
            <ScrollAreaPrimitive.Viewport
                ref={viewportRef}
                render={viewportRender}
                data-slot="scroll-area-viewport"
                className={cn(
                    "focus-visible:ring-ring/50 size-full rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:outline-1",
                    viewportClassName,
                )}
                {...viewportProps}
            >
                {children}
            </ScrollAreaPrimitive.Viewport>
            {overflowFadeClassName !== undefined && (
                <>
                    <div
                        aria-hidden="true"
                        data-slot="scroll-area-overflow-fade"
                        data-edge="top"
                        className={cn(
                            "pointer-events-none absolute start-1 end-3 top-0 z-[51] h-4 bg-gradient-to-b to-transparent opacity-0 transition-opacity group-data-[overflow-y-start]/scroll-area:opacity-100",
                            overflowFadeClassName,
                        )}
                    />
                    <div
                        aria-hidden="true"
                        data-slot="scroll-area-overflow-fade"
                        data-edge="bottom"
                        className={cn(
                            "pointer-events-none absolute start-1 end-3 bottom-0 z-[51] h-4 bg-gradient-to-t to-transparent opacity-0 transition-opacity group-data-[overflow-y-end]/scroll-area:opacity-100",
                            overflowFadeClassName,
                        )}
                    />
                </>
            )}
            <ScrollBar
                alwaysVisible={scrollbarAlwaysVisible}
                className={scrollbarClassName}
            />
            <ScrollAreaPrimitive.Corner />
        </ScrollAreaPrimitive.Root>
    );
}

function ScrollBar({
    alwaysVisible = false,
    className,
    orientation = "vertical",
    ...props
}: ScrollAreaPrimitive.Scrollbar.Props & { alwaysVisible?: boolean }) {
    return (
        <ScrollAreaPrimitive.Scrollbar
            data-slot="scroll-area-scrollbar"
            data-orientation={orientation}
            orientation={orientation}
            className={cn(
                "pointer-events-none flex touch-none p-px opacity-0 transition-opacity duration-150 select-none data-[hovering]:pointer-events-auto data-[hovering]:opacity-100 data-[scrolling]:pointer-events-auto data-[scrolling]:opacity-100 group-focus-within/scroll-area:pointer-events-auto group-focus-within/scroll-area:opacity-100 data-horizontal:h-2.5 data-horizontal:flex-col data-horizontal:border-t data-horizontal:border-t-transparent data-vertical:h-full data-vertical:w-2.5 data-vertical:border-l data-vertical:border-l-transparent",
                alwaysVisible && "pointer-events-auto opacity-100",
                className,
            )}
            {...props}
        >
            <ScrollAreaPrimitive.Thumb
                data-slot="scroll-area-thumb"
                className="bg-border relative flex-1 rounded-full"
            />
        </ScrollAreaPrimitive.Scrollbar>
    );
}

export { ScrollArea, ScrollBar };
