import { isApiError } from "@va/shared/lib/api-client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Loader<T> = (signal: AbortSignal) => Promise<T>;
interface Result<T> {
    request: { load: Loader<T>; enabled: boolean };
    data?: T;
    error?: string;
}

/** Quiet polling. Callers may retain previous data while a replacement request is pending. */
export const useComplianceData = <T>({
    load,
    errorMessage,
    retainPreviousData = false,
    enabled = true,
    poll = true,
}: {
    load: Loader<T>;
    errorMessage: string;
    retainPreviousData?: boolean;
    enabled?: boolean;
    poll?: boolean;
}): {
    data: T | undefined;
    error: string | undefined;
    loading: boolean;
    refresh: () => void;
} => {
    const [result, setResult] = useState<Result<T>>();
    const request = useMemo(() => ({ load, enabled }), [load, enabled]);
    const refreshRef = useRef<(() => void) | undefined>(undefined);
    const refresh = useCallback((): void => {
        refreshRef.current?.();
    }, []);

    useEffect(() => {
        refreshRef.current = undefined;
        if (!enabled) {
            return void 0;
        }
        const controller = new AbortController();
        let pending = false;
        let refreshQueued = false;
        const fetchData = (): void => {
            if (pending || controller.signal.aborted) {
                return;
            }
            pending = true;
            void load(controller.signal)
                .then(
                    (data) => {
                        if (controller.signal.aborted) {
                            return;
                        }
                        setResult({ request, data });
                    },
                    (error: unknown) => {
                        if (controller.signal.aborted) {
                            return;
                        }
                        const message =
                            error instanceof Error && error.message !== ""
                                ? error.message
                                : errorMessage;
                        const transient =
                            !isApiError(error) ||
                            error.status >= 500 ||
                            error.status === 408 ||
                            error.status === 429;
                        setResult((current) => {
                            // Only retain data for this request, never a failed replacement page/message.
                            const previous =
                                transient && current?.request === request
                                    ? current
                                    : undefined;
                            if (
                                current?.request === request &&
                                current.error === message &&
                                current.data === previous?.data
                            ) {
                                return current;
                            }
                            return { ...previous, request, error: message };
                        });
                    },
                )
                .finally(() => {
                    pending = false;
                    if (refreshQueued) {
                        refreshQueued = false;
                        fetchData();
                    }
                });
        };
        refreshRef.current = (): void => {
            if (pending) {
                refreshQueued = true;
            } else {
                fetchData();
            }
        };
        fetchData();
        const whileVisible = (): void => {
            if (document.visibilityState !== "hidden") {
                fetchData();
            }
        };
        const timer = poll ? window.setInterval(whileVisible, 5000) : undefined;
        if (poll) {
            document.addEventListener("visibilitychange", whileVisible);
        }
        return (): void => {
            controller.abort();
            window.clearInterval(timer);
            document.removeEventListener("visibilitychange", whileVisible);
        };
    }, [load, request, errorMessage, enabled, poll]);

    const current = result?.request === request ? result : undefined;
    return {
        data:
            current?.data ??
            (enabled &&
            current === undefined &&
            retainPreviousData &&
            result?.request.load !== load
                ? result?.data
                : undefined),
        error: current?.error,
        loading: enabled && current === undefined,
        refresh,
    };
};
