import { type JSX, type ReactNode, useMemo } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type { ChatCollectionKind } from "../lib/api";
import { createChatStore } from "../lib/store";
import { ChatStoreContext } from "./chat-store-context";

interface ChatStoreProviderProps {
    children: ReactNode;
    collectionKind?: ChatCollectionKind;
}

export const ChatStoreProvider = ({
    children,
    collectionKind,
}: ChatStoreProviderProps): JSX.Element => {
    const api = useAuthenticatedApi();

    const store = useMemo(
        () => createChatStore(api, { collectionKind }),
        [api, collectionKind],
    );

    return <ChatStoreContext value={store}>{children}</ChatStoreContext>;
};
