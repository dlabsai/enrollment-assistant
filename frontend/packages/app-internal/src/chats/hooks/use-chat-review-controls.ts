import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import type { ChatDetailResponse } from "../../chat/types";
import { formatChatTranscript } from "../lib/transcript";

export const usePersistentChatSummary = (
    storageKey: string,
): [boolean, (show: boolean) => void] => {
    const [showSummary, setShowSummary] = useState(() => {
        if (typeof window === "undefined") {
            return true;
        }
        const stored = window.localStorage.getItem(storageKey);
        return stored === null ? true : stored === "true";
    });

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        window.localStorage.setItem(storageKey, String(showSummary));
    }, [showSummary, storageKey]);

    return [showSummary, setShowSummary];
};

export const useCopyChatTranscript = (
    detail: ChatDetailResponse | undefined,
): (() => Promise<void>) =>
    useCallback(async (): Promise<void> => {
        if (detail === undefined) {
            return;
        }

        try {
            await navigator.clipboard.writeText(formatChatTranscript(detail));
            toast.success("Copied transcript");
        } catch {
            toast.error("Failed to copy transcript");
        }
    }, [detail]);
