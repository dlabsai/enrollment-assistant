import {
    type CSSProperties,
    type KeyboardEvent as ReactKeyboardEvent,
    type PointerEvent as ReactPointerEvent,
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react";

import {
    clampTraceSheetWidthFraction,
    getTraceSheetKeyboardWidth,
    resolveTraceSheetDefaultWidthFraction,
    TRACE_SHEET_EXPAND_ENTER_FRACTION,
    TRACE_SHEET_MIN_WIDTH_FRACTION,
} from "../lib/trace-layout";

const TRACE_SHEET_WIDTH_STORAGE_KEY = "internal-trace-sheet-width-fraction";

type TraceSheetPanelStyle = CSSProperties & {
    "--trace-sheet-width": string;
};

type TraceSheetDraftWidth = number | "expanded" | undefined;

interface TraceSheetResizeHandleProps {
    role: "separator";
    "aria-label": string;
    "aria-orientation": "vertical";
    "aria-valuemax": number;
    "aria-valuemin": number;
    "aria-valuenow": number;
    "aria-valuetext": string;
    onKeyDown: (event: ReactKeyboardEvent<HTMLDivElement>) => void;
    onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
    tabIndex: 0;
}

interface TraceSheetPanel {
    handleCancelResize: () => void;
    handleToggleExpanded: () => void;
    isExpanded: boolean;
    isResizing: boolean;
    panelStyle: TraceSheetPanelStyle;
    resizeHandleProps: TraceSheetResizeHandleProps;
}

const getInitialWidthFraction = (): number => {
    if (typeof window === "undefined") {
        return resolveTraceSheetDefaultWidthFraction(0);
    }
    try {
        const stored = window.localStorage.getItem(
            TRACE_SHEET_WIDTH_STORAGE_KEY,
        );
        if (stored !== null) {
            const parsed: unknown = JSON.parse(stored);
            if (typeof parsed === "number" && Number.isFinite(parsed)) {
                return clampTraceSheetWidthFraction(parsed);
            }
        }
    } catch {
        // Fall back to the viewport-aware default.
    }
    return resolveTraceSheetDefaultWidthFraction(window.innerWidth);
};

const storeWidthFraction = (fraction: number): void => {
    if (typeof window === "undefined") {
        return;
    }
    try {
        window.localStorage.setItem(
            TRACE_SHEET_WIDTH_STORAGE_KEY,
            JSON.stringify(fraction),
        );
    } catch {
        // Width persistence is best effort.
    }
};

export const useTraceSheetPanel = (): TraceSheetPanel => {
    const [widthFraction, setWidthFraction] = useState(getInitialWidthFraction);
    const [expanded, setExpanded] = useState(false);
    const [draftWidth, setDraftWidth] = useState<TraceSheetDraftWidth>();
    const dragTeardownRef = useRef<(() => void) | null>(null);

    const cancelResize = useCallback((): void => {
        dragTeardownRef.current?.();
        dragTeardownRef.current = null;
        setDraftWidth(undefined);
    }, []);

    useEffect(
        () => (): void => {
            dragTeardownRef.current?.();
            dragTeardownRef.current = null;
        },
        [],
    );

    const commitWidth = useCallback((fraction: number): void => {
        const clamped = Number(
            clampTraceSheetWidthFraction(fraction).toFixed(4),
        );
        setWidthFraction(clamped);
        storeWidthFraction(clamped);
    }, []);

    const onPointerDown = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>): void => {
            if (event.button !== 0 || typeof window === "undefined") {
                return;
            }
            event.preventDefault();
            cancelResize();

            let nextWidth: Exclude<TraceSheetDraftWidth, undefined> = expanded
                ? "expanded"
                : widthFraction;
            const {pointerId} = event;
            const previousUserSelect = document.body.style.userSelect;
            const previousCursor = document.body.style.cursor;

            const resizeAbortController = new AbortController();
            const teardown = (): void => {
                resizeAbortController.abort();
                document.body.style.userSelect = previousUserSelect;
                document.body.style.cursor = previousCursor;
            };

            const finish = (): void => {
                dragTeardownRef.current = null;
                setDraftWidth(undefined);
            };

            const onPointerMove = (moveEvent: PointerEvent): void => {
                if (moveEvent.pointerId !== pointerId) {
                    return;
                }
                const fraction = 1 - moveEvent.clientX / window.innerWidth;
                nextWidth =
                    fraction >= TRACE_SHEET_EXPAND_ENTER_FRACTION
                        ? "expanded"
                        : clampTraceSheetWidthFraction(fraction);
                setDraftWidth(nextWidth);
            };

            const onPointerUp = (upEvent: PointerEvent): void => {
                if (upEvent.pointerId !== pointerId) {
                    return;
                }
                teardown();
                if (nextWidth === "expanded") {
                    setExpanded(true);
                } else {
                    commitWidth(nextWidth);
                    setExpanded(false);
                }
                finish();
            };

            const onPointerCancel = (cancelEvent: PointerEvent): void => {
                if (cancelEvent.pointerId !== pointerId) {
                    return;
                }
                teardown();
                finish();
            };

            window.addEventListener("pointermove", onPointerMove, {
                signal: resizeAbortController.signal,
            });
            window.addEventListener("pointerup", onPointerUp, {
                signal: resizeAbortController.signal,
            });
            window.addEventListener("pointercancel", onPointerCancel, {
                signal: resizeAbortController.signal,
            });
            document.body.style.userSelect = "none";
            document.body.style.cursor = "ew-resize";
            setDraftWidth(nextWidth);
            dragTeardownRef.current = teardown;
        },
        [cancelResize, commitWidth, expanded, widthFraction],
    );

    const onKeyDown = useCallback(
        (event: ReactKeyboardEvent<HTMLDivElement>): void => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
                return;
            }
            event.preventDefault();
            const nextWidth = getTraceSheetKeyboardWidth(
                widthFraction,
                expanded,
                event.key === "ArrowLeft" ? "grow" : "shrink",
            );
            if (nextWidth === "expanded") {
                setExpanded(true);
                return;
            }
            commitWidth(nextWidth);
            setExpanded(false);
        },
        [commitWidth, expanded, widthFraction],
    );

    const handleToggleExpanded = useCallback((): void => {
        cancelResize();
        setExpanded((value) => !value);
    }, [cancelResize]);

    const isResizing = draftWidth !== undefined;
    const effectiveExpanded =
        draftWidth === "expanded" || (draftWidth === undefined && expanded);
    const effectiveWidthFraction =
        typeof draftWidth === "number" ? draftWidth : widthFraction;
    const widthPercent = effectiveExpanded
        ? 100
        : Math.round(effectiveWidthFraction * 100);

    return {
        handleCancelResize: cancelResize,
        handleToggleExpanded,
        isExpanded: effectiveExpanded,
        isResizing,
        panelStyle: {
            "--trace-sheet-width": effectiveExpanded
                ? "100vw"
                : `${effectiveWidthFraction * 100}vw`,
        },
        resizeHandleProps: {
            role: "separator",
            "aria-label": "Resize trace sheet",
            "aria-orientation": "vertical",
            "aria-valuemax": 100,
            "aria-valuemin": Math.round(TRACE_SHEET_MIN_WIDTH_FRACTION * 100),
            "aria-valuenow": widthPercent,
            "aria-valuetext": effectiveExpanded
                ? "Full viewport"
                : `${widthPercent}% of viewport`,
            onKeyDown,
            onPointerDown,
            tabIndex: 0,
        },
    };
};
