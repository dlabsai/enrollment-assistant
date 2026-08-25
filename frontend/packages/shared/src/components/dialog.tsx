import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@va/shared/components/ui/alert-dialog";
import { buttonVariants } from "@va/shared/components/ui/button";
import { logger } from "@va/shared/lib/logger";
import type { JSX, ReactNode } from "react";

interface ConfirmDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title?: string;
    description?: ReactNode;
    confirmLabel?: string;
    cancelLabel?: string;
    onConfirm?: () => void | Promise<void>;
}

export const ConfirmDialog = ({
    open,
    onOpenChange,
    title = "Confirm",
    description,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    onConfirm,
}: ConfirmDialogProps): JSX.Element => {
    const normalizedConfirmLabel = confirmLabel.trim().toLowerCase();
    const normalizedTitle = title.trim().toLowerCase();

    const isDestructiveConfirm =
        normalizedConfirmLabel === "delete" ||
        normalizedConfirmLabel === "discard" ||
        normalizedTitle.includes("delete") ||
        normalizedTitle.includes("discard");

    const resolvedDescription = description ?? undefined;
    const handleConfirm = async (): Promise<void> => {
        if (onConfirm) {
            try {
                await onConfirm();
            } catch (error) {
                logger.error(error);
            }
        }
        onOpenChange(false);
    };

    return (
        <AlertDialog
            onOpenChange={onOpenChange}
            open={open}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    {resolvedDescription !== undefined && (
                        <AlertDialogDescription>
                            {resolvedDescription}
                        </AlertDialogDescription>
                    )}
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel>{cancelLabel}</AlertDialogCancel>
                    <AlertDialogAction
                        className={
                            isDestructiveConfirm
                                ? buttonVariants({ variant: "destructive" })
                                : undefined
                        }
                        onClick={(): void => {
                            void handleConfirm();
                        }}
                    >
                        {confirmLabel}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

interface ErrorDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title?: string;
    description?: ReactNode;
    okLabel?: string;
}

export const ErrorDialog = ({
    open,
    onOpenChange,
    title = "Error",
    description,
    okLabel = "OK",
}: ErrorDialogProps): JSX.Element => {
    const resolvedDescription = description ?? undefined;
    return (
        <AlertDialog
            onOpenChange={onOpenChange}
            open={open}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    {resolvedDescription !== undefined && (
                        <AlertDialogDescription>
                            {resolvedDescription}
                        </AlertDialogDescription>
                    )}
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogAction
                        onClick={(): void => {
                            onOpenChange(false);
                        }}
                    >
                        {okLabel}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};
