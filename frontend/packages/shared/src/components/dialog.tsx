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
import { Spinner } from "@va/shared/components/ui/spinner";
import { logger } from "@va/shared/lib/logger";
import { type JSX, type ReactNode, useRef, useState } from "react";

interface ConfirmDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title?: string;
    description?: ReactNode;
    confirmLabel?: string;
    cancelLabel?: string;
    onConfirm?: () => void | Promise<void>;
}

type ConfirmDialogContentProps = Omit<ConfirmDialogProps, "open"> & {
    onPendingChange: (pending: boolean) => void;
    pending: boolean;
};

const ConfirmDialogContent = ({
    onOpenChange,
    onPendingChange,
    pending,
    title = "Confirm",
    description,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    onConfirm,
}: ConfirmDialogContentProps): JSX.Element => {
    const pendingRef = useRef(false);
    const normalizedConfirmLabel = confirmLabel.trim().toLowerCase();
    const normalizedTitle = title.trim().toLowerCase();
    const isDestructiveConfirm =
        normalizedConfirmLabel === "delete" ||
        normalizedConfirmLabel === "discard" ||
        normalizedTitle.includes("delete") ||
        normalizedTitle.includes("discard");
    const handleConfirm = async (): Promise<void> => {
        if (pendingRef.current) {
            return;
        }
        pendingRef.current = true;
        onPendingChange(true);
        try {
            await onConfirm?.();
        } catch (error) {
            logger.error(error);
        } finally {
            onPendingChange(false);
            onOpenChange(false);
        }
    };

    return (
        <AlertDialogContent>
            <AlertDialogHeader>
                <AlertDialogTitle>{title}</AlertDialogTitle>
                {description !== undefined && (
                    <AlertDialogDescription>
                        {description}
                    </AlertDialogDescription>
                )}
            </AlertDialogHeader>
            <AlertDialogFooter>
                <AlertDialogCancel disabled={pending}>
                    {cancelLabel}
                </AlertDialogCancel>
                <AlertDialogAction
                    aria-busy={pending}
                    className={
                        isDestructiveConfirm
                            ? buttonVariants({ variant: "destructive" })
                            : undefined
                    }
                    disabled={pending}
                    onClick={(): void => {
                        void handleConfirm();
                    }}
                >
                    {pending && <Spinner />}
                    {confirmLabel}
                </AlertDialogAction>
            </AlertDialogFooter>
        </AlertDialogContent>
    );
};

export const ConfirmDialog = ({
    open,
    onOpenChange,
    ...contentProps
}: ConfirmDialogProps): JSX.Element => {
    const [pending, setPending] = useState(false);
    return (
        <AlertDialog
            onOpenChange={(nextOpen) => {
                if (!pending) {
                    onOpenChange(nextOpen);
                }
            }}
            open={open}
        >
            <ConfirmDialogContent
                key={open ? "open" : "closed"}
                {...contentProps}
                onOpenChange={onOpenChange}
                onPendingChange={setPending}
                pending={pending}
            />
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
