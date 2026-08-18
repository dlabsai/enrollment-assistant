import {
    type RefObject,
    type UIEventHandler,
    useCallback,
    useRef,
} from "react";

const SCROLL_BOTTOM_TOLERANCE_PX = 4;

interface UseStickyBottomScrollResult {
    containerRef: RefObject<HTMLDivElement | null>;
    handleScroll: UIEventHandler<HTMLDivElement>;
    resetStickToBottom: () => void;
    scrollToBottomIfPinned: () => void;
}

const isScrolledToBottom = (element: HTMLDivElement): boolean =>
    element.scrollHeight - element.scrollTop - element.clientHeight <=
    SCROLL_BOTTOM_TOLERANCE_PX;

export const useStickyBottomScroll = (): UseStickyBottomScrollResult => {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const shouldStickToBottomRef = useRef(true);

    const handleScroll = useCallback<UIEventHandler<HTMLDivElement>>(
        (event) => {
            shouldStickToBottomRef.current = isScrolledToBottom(
                event.currentTarget,
            );
        },
        [],
    );

    const resetStickToBottom = useCallback((): void => {
        shouldStickToBottomRef.current = true;
    }, []);

    const scrollToBottomIfPinned = useCallback((): void => {
        if (!shouldStickToBottomRef.current) {
            return;
        }

        requestAnimationFrame(() => {
            const container = containerRef.current;
            if (container === null || !shouldStickToBottomRef.current) {
                return;
            }

            container.scrollTop = container.scrollHeight;
            shouldStickToBottomRef.current = true;
        });
    }, []);

    return {
        containerRef,
        handleScroll,
        resetStickToBottom,
        scrollToBottomIfPinned,
    };
};
