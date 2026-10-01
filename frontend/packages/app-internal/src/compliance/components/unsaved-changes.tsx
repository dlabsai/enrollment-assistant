import { useBlocker } from "@tanstack/react-router";
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
import { type JSX, useCallback, useEffect } from "react";

export const UnsavedChanges = ({
    dirty,
    pending = false,
    onDiscard,
}: {
    dirty: boolean;
    pending?: boolean;
    onDiscard: () => void;
}): JSX.Element => {
    const shouldBlockNavigation = dirty || pending;
    const shouldBlock = useCallback(
        () => shouldBlockNavigation,
        [shouldBlockNavigation],
    );
    const blocker = useBlocker({
        shouldBlockFn: shouldBlock,
        enableBeforeUnload: shouldBlockNavigation,
        withResolver: true,
    });
    useEffect(() => {
        if (!shouldBlockNavigation && blocker.status === "blocked") {
            blocker.reset();
        }
    }, [blocker, shouldBlockNavigation]);
    return (
        <AlertDialog
            onOpenChange={(open) => {
                if (!open && blocker.status === "blocked") {
                    blocker.reset();
                }
            }}
            open={blocker.status === "blocked"}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>
                        {pending ? "Save in progress" : "Leave without saving?"}
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                        {pending
                            ? "Wait for the save to finish before leaving this page."
                            : "Your unsaved text will be lost. Stay on this page to save it first."}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel>Keep editing</AlertDialogCancel>
                    <AlertDialogAction
                        className={buttonVariants({ variant: "destructive" })}
                        disabled={pending}
                        onClick={() => {
                            if (pending || blocker.status !== "blocked") {
                                return;
                            }
                            onDiscard();
                            blocker.proceed();
                        }}
                    >
                        Discard
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};
