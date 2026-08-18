import { type JSX, type ReactNode, useMemo } from "react";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { createInstructionsStore } from "../lib/store";
import { InstructionsStoreContext } from "./instructions-store-context";

interface InstructionsStoreProviderProps {
    children: ReactNode;
}

export const InstructionsStoreProvider = ({
    children,
}: InstructionsStoreProviderProps): JSX.Element => {
    const api = useAuthenticatedApi();
    const { user } = useAuth();
    const userId = user?.id;

    const store = useMemo(() => {
        if (userId === undefined) {
            throw new Error("InstructionsStoreProvider requires an authenticated user");
        }
        return createInstructionsStore(api, userId);
    }, [api, userId]);

    return (
        <InstructionsStoreContext value={store}>
            {children}
        </InstructionsStoreContext>
    );
};
