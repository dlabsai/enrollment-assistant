import { useBlocker } from "@tanstack/react-router";
import { ConfirmDialog } from "@va/shared/components/dialog";
import type { JSX } from "react";

export const UnsavedChanges = ({ dirty }: { dirty: boolean }): JSX.Element => {
    const blocker = useBlocker({
        shouldBlockFn: () => dirty,
        enableBeforeUnload: dirty,
        withResolver: true,
    });
    return (
        <ConfirmDialog
            cancelLabel="Keep editing"
            confirmLabel="Discard"
            description="Your unsaved text will be lost. Stay on this page to save it first."
            onConfirm={() => {
                blocker.proceed?.();
            }}
            onOpenChange={(open) => {
                if (!open) {
                    blocker.reset?.();
                }
            }}
            open={blocker.status === "blocked"}
            title="Leave without saving?"
        />
    );
};
