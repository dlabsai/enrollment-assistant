import { isAbortError } from "@va/shared/lib/api-client";
import { useCallback, useEffect, useMemo, useState } from "react";

type AsyncDataLoader<T> = (signal: AbortSignal) => Promise<T>;

interface AsyncDataRequest<T> {
    clearDataOnError: boolean;
    enabled: boolean;
    errorMessage: string;
    load: AsyncDataLoader<T>;
    refreshVersion: number;
}

interface AsyncDataState<T> {
    completedRequest?: AsyncDataRequest<T>;
    data: T;
    error?: string;
    hasSucceeded: boolean;
    initialData: T;
}

interface UseAsyncDataOptions<T> {
    clearDataOnError?: boolean;
    enabled?: boolean;
    errorMessage: string;
    initialData: T;
    load: AsyncDataLoader<T>;
}

interface UseAsyncDataResult<T> {
    data: T;
    error: string | undefined;
    hasLoaded: boolean;
    hasSucceeded: boolean;
    loading: boolean;
    refresh: () => void;
}

export const useAsyncData = <T>({
    clearDataOnError = false,
    enabled = true,
    errorMessage,
    initialData,
    load,
}: UseAsyncDataOptions<T>): UseAsyncDataResult<T> => {
    const [refreshVersion, setRefreshVersion] = useState(0);
    const request = useMemo<AsyncDataRequest<T>>(
        () => ({
            clearDataOnError,
            enabled,
            errorMessage,
            load,
            refreshVersion,
        }),
        [clearDataOnError, enabled, errorMessage, load, refreshVersion],
    );
    const [state, setState] = useState<AsyncDataState<T>>(() => ({
        data: initialData,
        hasSucceeded: false,
        initialData,
    }));

    useEffect(() => {
        const controller = new AbortController();
        if (request.enabled) {
            void request.load(controller.signal).then(
                (data) => {
                    if (!controller.signal.aborted) {
                        setState((current) => ({
                            ...current,
                            completedRequest: request,
                            data,
                            error: undefined,
                            hasSucceeded: true,
                        }));
                    }
                },
                (error: unknown) => {
                    if (controller.signal.aborted || isAbortError(error)) {
                        return;
                    }
                    setState((current) => ({
                        ...current,
                        completedRequest: request,
                        data: request.clearDataOnError
                            ? current.initialData
                            : current.data,
                        error:
                            error instanceof Error && error.message !== ""
                                ? error.message
                                : request.errorMessage,
                    }));
                },
            );
        }

        return (): void => {
            controller.abort();
        };
    }, [request]);

    const refresh = useCallback((): void => {
        setRefreshVersion((current) => current + 1);
    }, []);
    const requestHasCompleted = state.completedRequest === request;

    return {
        data: request.enabled ? state.data : state.initialData,
        error: requestHasCompleted ? state.error : undefined,
        hasLoaded: state.completedRequest !== undefined,
        hasSucceeded: state.hasSucceeded,
        loading: request.enabled && !requestHasCompleted,
        refresh,
    };
};
