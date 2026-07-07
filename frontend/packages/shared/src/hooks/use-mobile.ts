import * as React from "react";

const MOBILE_BREAKPOINT = 768;

export const useIsMobile = (): boolean => {
    const [isMobile, setIsMobile] = React.useState<boolean | undefined>(() =>
        typeof window === "undefined"
            ? undefined
            : window.innerWidth < MOBILE_BREAKPOINT,
    );

    React.useEffect(() => {
        const mql = window.matchMedia(
            `(max-width: ${MOBILE_BREAKPOINT - 1}px)`,
        );
        const handleChange = (): void => {
            setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
        };

        mql.addEventListener("change", handleChange);

        return (): void => {
            mql.removeEventListener("change", handleChange);
        };
    }, []);

    return Boolean(isMobile);
};
