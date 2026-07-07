import { useNavigate } from "@tanstack/react-router";
import { Button } from "@va/shared/components/ui/button";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { SearchCheck } from "lucide-react";
import type { JSX } from "react";
import { toast } from "sonner";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
import { createInvestigationChat } from "../lib/api";

interface InvestigationButtonProps {
    conversationId?: string;
    disabled?: boolean;
    messageId: string;
    withProvider?: boolean;
}

const InvestigationButtonContent = ({
    conversationId,
    disabled = false,
    messageId,
}: Omit<InvestigationButtonProps, "withProvider">): JSX.Element | undefined => {
    const api = useAuthenticatedApi();
    const navigate = useNavigate();
    const { user } = useAuth();

    if (
        !hasPermission(user, "access_investigations") ||
        conversationId === undefined ||
        conversationId.startsWith("__temp_")
    ) {
        return undefined;
    }

    const startInvestigation = async (): Promise<void> => {
        try {
            const investigationId = await createInvestigationChat(api, {
                conversationId,
                messageId,
            });
            await navigate({
                to: "/investigate",
                search: { chat: investigationId, message: undefined },
            });
        } catch (error_) {
            toast.error(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to create investigation",
            );
        }
    };

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        aria-label="Investigate response"
                        className="text-muted-foreground rounded-full transition"
                        disabled={disabled}
                        onClick={() => {
                            void startInvestigation();
                        }}
                        size="icon-sm"
                        type="button"
                        variant="ghost"
                    >
                        <SearchCheck className="size-4" />
                        <span className="sr-only">Investigate response</span>
                    </Button>
                }
            />
            <TooltipContent>Investigate response</TooltipContent>
        </Tooltip>
    );
};

export const InvestigationButton = ({
    withProvider = false,
    ...props
}: InvestigationButtonProps): JSX.Element | undefined => {
    const button = <InvestigationButtonContent {...props} />;
    if (!withProvider) {
        return button;
    }
    return <TooltipProvider delay={0}>{button}</TooltipProvider>;
};
