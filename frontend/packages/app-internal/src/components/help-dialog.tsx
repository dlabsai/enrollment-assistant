import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import { HelpCircle } from "lucide-react";
import type { JSX, ReactNode } from "react";

interface HelpButtonProps {
    label?: string;
    iconOnly?: boolean;
    onClick: () => void;
}

export const HelpButton = ({
    label = "Help",
    iconOnly = false,
    onClick,
}: HelpButtonProps): JSX.Element => (
    <Button
        aria-label={iconOnly ? label : undefined}
        onClick={onClick}
        size={iconOnly ? "icon-sm" : "sm"}
        type="button"
        variant="outline"
    >
        <HelpCircle data-icon={iconOnly ? undefined : "inline-start"} />
        {!iconOnly && label}
    </Button>
);

interface HelpDialogProps {
    children: ReactNode;
    onOpenChange: (open: boolean) => void;
    open: boolean;
    title: string;
}

export const HelpDialog = ({
    children,
    onOpenChange,
    open,
    title,
}: HelpDialogProps): JSX.Element => (
    <Dialog
        onOpenChange={onOpenChange}
        open={open}
    >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
            <DialogHeader>
                <DialogTitle>{title}</DialogTitle>
            </DialogHeader>
            {children}
            <DialogFooter showCloseButton />
        </DialogContent>
    </Dialog>
);
