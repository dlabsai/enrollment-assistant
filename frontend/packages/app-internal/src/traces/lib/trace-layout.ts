export type TraceLayoutScope = "page" | "peek";

export const TRACE_SHEET_WIDTH_CLASS =
    "!w-screen !max-w-none md:!w-[var(--trace-sheet-width)]";

export const TRACE_SHEET_MIN_WIDTH_FRACTION = 0.4;
const TRACE_SHEET_MAX_WIDTH_FRACTION = 0.9;
const TRACE_SHEET_DEFAULT_WIDTH_FRACTION = 0.5;
export const TRACE_SHEET_EXPAND_ENTER_FRACTION = 0.95;
const TRACE_SHEET_KEYBOARD_RESIZE_STEP = 0.05;
const TRACE_SHEET_MAX_DEFAULT_WIDTH_PX = 1400;

export type TraceSheetKeyboardWidth = number | "expanded";

export const clampTraceSheetWidthFraction = (fraction: number): number =>
    Math.min(
        TRACE_SHEET_MAX_WIDTH_FRACTION,
        Math.max(TRACE_SHEET_MIN_WIDTH_FRACTION, fraction),
    );

export const getTraceSheetKeyboardWidth = (
    widthFraction: number,
    expanded: boolean,
    direction: "grow" | "shrink",
): TraceSheetKeyboardWidth => {
    if (expanded) {
        return direction === "grow"
            ? "expanded"
            : TRACE_SHEET_MAX_WIDTH_FRACTION;
    }
    const nextWidth =
        widthFraction +
        (direction === "grow"
            ? TRACE_SHEET_KEYBOARD_RESIZE_STEP
            : -TRACE_SHEET_KEYBOARD_RESIZE_STEP);
    return nextWidth >= TRACE_SHEET_EXPAND_ENTER_FRACTION
        ? "expanded"
        : clampTraceSheetWidthFraction(nextWidth);
};

export const resolveTraceSheetDefaultWidthFraction = (
    viewportWidthPx: number,
): number => {
    if (!(viewportWidthPx > 0)) {
        return TRACE_SHEET_DEFAULT_WIDTH_FRACTION;
    }
    return Math.max(
        TRACE_SHEET_MIN_WIDTH_FRACTION,
        Math.min(
            TRACE_SHEET_DEFAULT_WIDTH_FRACTION,
            TRACE_SHEET_MAX_DEFAULT_WIDTH_PX / viewportWidthPx,
        ),
    );
};

export const TRACE_NAVIGATION_PANEL_MIN_PX = 260;
export const TRACE_DETAIL_PANEL_MIN_PX = 360;
const TRACE_RESIZE_HANDLE_PX = 1;
export const TRACE_BOTH_PANELS_MIN_WIDTH_PX =
    TRACE_NAVIGATION_PANEL_MIN_PX +
    TRACE_DETAIL_PANEL_MIN_PX +
    TRACE_RESIZE_HANDLE_PX;

const TRACE_DETAIL_COMFORTABLE_TARGET_PX = 560;
const TRACE_NAVIGATION_COMFORTABLE_MIN_PX = 340;
const TRACE_NAVIGATION_COMFORTABLE_MAX_PX = 460;

export const getTraceNavigationDefaultWidth = (
    containerWidthPx: number,
): number => {
    const comfortableWidth = Math.min(
        TRACE_NAVIGATION_COMFORTABLE_MAX_PX,
        Math.max(
            TRACE_NAVIGATION_COMFORTABLE_MIN_PX,
            containerWidthPx - TRACE_DETAIL_COMFORTABLE_TARGET_PX,
        ),
    );
    const widthWithDetailMinimum =
        containerWidthPx - TRACE_DETAIL_PANEL_MIN_PX - TRACE_RESIZE_HANDLE_PX;
    return Math.max(
        TRACE_NAVIGATION_PANEL_MIN_PX,
        Math.min(comfortableWidth, widthWithDetailMinimum),
    );
};

export const getTraceNavigationDefaultPercent = (
    containerWidthPx: number,
): number | undefined => {
    if (!(containerWidthPx > 0)) {
        return undefined;
    }
    const layoutWidthPx = Math.max(
        containerWidthPx,
        TRACE_BOTH_PANELS_MIN_WIDTH_PX,
    );
    return (
        (getTraceNavigationDefaultWidth(layoutWidthPx) / layoutWidthPx) * 100
    );
};
