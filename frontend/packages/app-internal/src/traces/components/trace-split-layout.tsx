import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
    useDefaultLayout,
} from "@va/shared/components/ui/resizable";
import {
    type JSX,
    type ReactNode,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import {
    getTraceNavigationDefaultPercent,
    TRACE_BOTH_PANELS_MIN_WIDTH_PX,
    TRACE_DETAIL_PANEL_MIN_PX,
    TRACE_NAVIGATION_PANEL_MIN_PX,
    type TraceLayoutScope,
} from "../lib/trace-layout";

interface TraceSplitLayoutProps {
    detail: ReactNode;
    navigation: ReactNode;
    scope?: TraceLayoutScope;
}

const NAVIGATION_PANEL_ID = "trace-layout-navigation";
const DETAIL_PANEL_ID = "trace-layout-detail";
const NOOP_LAYOUT_STORAGE = {
    getItem: (): null => null,
    setItem: (): void => undefined,
};

export const TraceSplitLayout = ({
    detail,
    navigation,
    scope = "page",
}: TraceSplitLayoutProps): JSX.Element => {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const [containerWidth, setContainerWidth] = useState<number>();

    useLayoutEffect((): (() => void) | undefined => {
        const container = containerRef.current;
        if (container === null) {
            return undefined;
        }
        const observer = new ResizeObserver(([entry]) => {
            const width = entry?.contentRect.width ?? 0;
            if (width > 0) {
                setContainerWidth(width);
                observer.disconnect();
            }
        });
        observer.observe(container);
        return () => {
            observer.disconnect();
        };
    }, []);

    const navigationPercent =
        containerWidth === undefined
            ? undefined
            : getTraceNavigationDefaultPercent(containerWidth);
    const groupId = `internal-trace-layout-${scope}-v1`;
    const storage =
        typeof window === "undefined"
            ? NOOP_LAYOUT_STORAGE
            : window.localStorage;
    const { defaultLayout, onLayoutChanged } = useDefaultLayout({
        id: groupId,
        panelIds: [NAVIGATION_PANEL_ID, DETAIL_PANEL_ID],
        storage,
    });
    const computedDefaultLayout = useMemo(
        () =>
            navigationPercent === undefined
                ? undefined
                : {
                      [NAVIGATION_PANEL_ID]: navigationPercent,
                      [DETAIL_PANEL_ID]: 100 - navigationPercent,
                  },
        [navigationPercent],
    );

    return (
        <div
            className="h-full min-h-0 w-full overflow-x-auto overflow-y-hidden"
            ref={containerRef}
        >
            {navigationPercent === undefined ? undefined : (
                <ResizablePanelGroup
                    className="h-full min-h-0"
                    defaultLayout={defaultLayout ?? computedDefaultLayout}
                    id={groupId}
                    onLayoutChanged={onLayoutChanged}
                    orientation="horizontal"
                    style={{
                        minWidth: `${TRACE_BOTH_PANELS_MIN_WIDTH_PX}px`,
                    }}
                >
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        groupResizeBehavior="preserve-pixel-size"
                        id={NAVIGATION_PANEL_ID}
                        minSize={`${TRACE_NAVIGATION_PANEL_MIN_PX}px`}
                    >
                        {navigation}
                    </ResizablePanel>
                    <ResizableHandle withHandle />
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        id={DETAIL_PANEL_ID}
                        minSize={`${TRACE_DETAIL_PANEL_MIN_PX}px`}
                    >
                        {detail}
                    </ResizablePanel>
                </ResizablePanelGroup>
            )}
        </div>
    );
};
