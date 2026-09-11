import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardDescription,
    CardFooter,
    CardHeader,
} from "@va/shared/components/ui/card";
import { isApiError } from "@va/shared/lib/api-client";
import { type JSX, type ReactNode, useState } from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { formatTableTimestamp } from "../../lib/date-format";
import { decisionLabel } from "../lib/presentation";
import type { Decision, DecisionState, Finding } from "../types";

export const FindingCard = ({
    finding,
    onSaved,
    onReload,
    nextAction,
    previousAction,
}: {
    finding: Finding;
    onSaved: () => void;
    onReload: () => void;
    nextAction: ReactNode;
    previousAction: ReactNode;
}): JSX.Element => {
    const api = useAuthenticatedApi();
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string>();
    const [saved, setSaved] = useState<Decision>();
    const [changing, setChanging] = useState(false);
    const latest =
        saved && saved.revision > finding.revision
            ? saved
            : finding.decisions.at(0);
    const state = latest?.state ?? finding.state;
    const attribution = latest
        ? `${decisionLabel(state)} by ${latest.reviewer} · ${formatTableTimestamp(latest.created_at)}`
        : undefined;
    const showDecisionActions = state === "needs_review" || changing;
    const reload = (): void => {
        setError(undefined);
        onReload();
    };
    const save = async (decision: DecisionState): Promise<void> => {
        setSaving(true);
        setError(undefined);
        try {
            const result = await api.post<Decision>(
                `/compliance/flags/${finding.id}/decision`,
                {
                    state: decision,
                    expected_revision: Math.max(
                        finding.revision,
                        saved?.revision ?? 0,
                    ),
                },
            );
            setSaved(result);
            setChanging(false);
            toast.success(
                decision === "confirmed" ? "Flag confirmed." : "Flag dismissed.",
            );
            onSaved();
        } catch (error_) {
            if (isApiError(error_) && error_.status === 412) {
                setSaved(undefined);
                setChanging(false);
                onReload();
                toast.info("Decision changed. Review the latest decision.");
                return;
            }
            setError(
                isApiError(error_)
                    ? error_.detail
                    : error_ instanceof Error
                      ? error_.message
                      : "Could not save. Please try again.",
            );
        } finally {
            setSaving(false);
        }
    };
    return (
        <Card
            aria-busy={saving}
            className="h-48"
            size="sm"
        >
            <CardHeader className="min-h-0 flex-1 overflow-y-auto">
                <CardDescription className="break-words whitespace-pre-wrap">
                    {finding.explanation}
                </CardDescription>
                {error !== undefined && (
                    <Alert variant="destructive">
                        <AlertDescription>
                            {error}
                            <div>
                                <Button
                                    onClick={reload}
                                    variant="outline"
                                >
                                    Reload flag
                                </Button>
                            </div>
                        </AlertDescription>
                    </Alert>
                )}
            </CardHeader>
            <CardFooter
                className="shrink-0 flex-col gap-2"
                variant="plain"
            >
                <CardDescription
                    className="h-5 w-full shrink-0 truncate text-center"
                    title={attribution}
                >
                    {attribution}
                </CardDescription>
                <div className="flex gap-2">
                    {showDecisionActions ? (
                        <>
                            <Button
                                disabled={saving}
                                onClick={() => {
                                    void save("confirmed");
                                }}
                                pressMotion={false}
                            >
                                Confirm
                            </Button>
                            <Button
                                disabled={saving}
                                onClick={() => {
                                    void save("dismissed");
                                }}
                                pressMotion={false}
                                variant="outline"
                            >
                                Dismiss
                            </Button>
                        </>
                    ) : (
                        <Button
                            onClick={() => {
                                setChanging(true);
                            }}
                            pressMotion={false}
                            variant="outline"
                        >
                            Change decision
                        </Button>
                    )}
                </div>
                <div className="flex gap-2">
                    {previousAction}
                    {nextAction}
                </div>
            </CardFooter>
        </Card>
    );
};
