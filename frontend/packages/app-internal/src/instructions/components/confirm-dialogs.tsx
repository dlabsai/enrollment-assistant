import { ConfirmDialog } from "@va/shared/components/dialog";
import type { JSX } from "react";

import {
    useInstructionsActions,
    useInstructionsStore,
} from "../contexts/instructions-store-context";
import type { ConfirmDialogAction } from "../types";

const DIALOG_CONFIGS: Record<
    ConfirmDialogAction,
    { title: string; description: string; confirmLabel: string }
> = {
    "delete-version": {
        title: "Delete saved version of the instructions",
        description:
            "Are you sure you want to delete this saved version of the instructions? This action cannot be undone.",
        confirmLabel: "Delete",
    },
    "switch-version": {
        title: "Discard drafts",
        description:
            "You have unsaved changes. Switching to another saved version of the instructions will discard all your drafts. Are you sure?",
        confirmLabel: "Discard",
    },
    "select-default": {
        title: "Discard drafts",
        description:
            "You have unsaved changes. Selecting Default will discard all your drafts. Are you sure?",
        confirmLabel: "Discard",
    },
    "reset-template": {
        title: "Discard draft",
        description: "Are you sure you want to discard your changes?",
        confirmLabel: "Discard",
    },
};

export const ConfirmDialogs = (): JSX.Element | undefined => {
    const confirmDialogAction = useInstructionsStore(
        (state) => state.confirmDialogAction,
    );
    const { closeConfirmDialog, confirmAction } = useInstructionsActions();

    if (confirmDialogAction === undefined) {
        return undefined;
    }

    const config = DIALOG_CONFIGS[confirmDialogAction];

    const handleConfirm = async (): Promise<void> => {
        await confirmAction();
    };

    const handleOpenChange = (open: boolean): void => {
        if (!open) {
            closeConfirmDialog();
        }
    };

    return (
        <ConfirmDialog
            cancelLabel="Cancel"
            confirmLabel={config.confirmLabel}
            description={config.description}
            onConfirm={handleConfirm}
            onOpenChange={handleOpenChange}
            open
            title={config.title}
        />
    );
};
