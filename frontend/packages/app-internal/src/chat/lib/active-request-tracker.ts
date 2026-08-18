interface ActiveRequestHandle {
    isCurrent: () => boolean;
    moveTo: (key: string) => boolean;
    finish: () => void;
}

interface ActiveRequestTracker {
    start: (key: string) => ActiveRequestHandle;
    invalidate: (key: string) => void;
}

export const createActiveRequestTracker = (): ActiveRequestTracker => {
    const activeTokens = new Map<string, symbol>();

    return {
        start: (key: string): ActiveRequestHandle => {
            const token = Symbol(key);
            let activeKey = key;
            activeTokens.set(key, token);

            const isCurrent = (): boolean =>
                activeTokens.get(activeKey) === token;

            return {
                isCurrent,
                moveTo: (nextKey: string): boolean => {
                    if (nextKey === activeKey) {
                        return isCurrent();
                    }

                    const wasCurrent = isCurrent();
                    if (wasCurrent) {
                        activeTokens.delete(activeKey);
                    }
                    activeKey = nextKey;
                    if (wasCurrent && !activeTokens.has(nextKey)) {
                        activeTokens.set(nextKey, token);
                    }
                    return isCurrent();
                },
                finish: (): void => {
                    if (isCurrent()) {
                        activeTokens.delete(activeKey);
                    }
                },
            };
        },
        invalidate: (key: string): void => {
            activeTokens.delete(key);
        },
    };
};
