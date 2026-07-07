import type { GroundingSourceStatus, MessageSourceUsed } from "@va/shared/types";
import { useCallback, useState } from "react";

export interface MessageSourcePanelMessage {
    id: string;
    role: "user" | "assistant";
    toolSourcesUsed?: MessageSourceUsed[];
    groundingSourcesUsed?: MessageSourceUsed[];
    groundingSourceStatus?: GroundingSourceStatus | null;
}

export interface MessageSourcePanelState {
    sourcesOpenMessageIds: Set<string>;
    toolSourcesOpenMessageIds: Set<string>;
    toggleSourcesPanel: (messageId: string) => void;
    toggleToolSourcesPanel: (messageId: string) => void;
}

export const useMessageSourcePanelState = (): MessageSourcePanelState => {
    const [sourcesOpenMessageIds, setSourcesOpenMessageIds] = useState<Set<string>>(
        () => new Set(),
    );
    const [toolSourcesOpenMessageIds, setToolSourcesOpenMessageIds] = useState<Set<string>>(
        () => new Set(),
    );

    const toggleSourcesPanel = useCallback((messageId: string): void => {
        setSourcesOpenMessageIds((current) => {
            const next = new Set(current);
            if (next.has(messageId)) {
                next.delete(messageId);
            } else {
                next.add(messageId);
            }
            return next;
        });
    }, []);

    const toggleToolSourcesPanel = useCallback((messageId: string): void => {
        setToolSourcesOpenMessageIds((current) => {
            const next = new Set(current);
            if (next.has(messageId)) {
                next.delete(messageId);
            } else {
                next.add(messageId);
            }
            return next;
        });
    }, []);

    return {
        sourcesOpenMessageIds,
        toolSourcesOpenMessageIds,
        toggleSourcesPanel,
        toggleToolSourcesPanel,
    };
};
