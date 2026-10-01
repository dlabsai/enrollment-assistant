import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { Textarea } from "@va/shared/components/ui/textarea";
import { isApiError } from "@va/shared/lib/api-client";
import {
    type JSX,
    type ReactNode,
    useLayoutEffect,
    useRef,
    useState,
} from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { formatTableTimestamp } from "../../lib/date-format";
import { decisionLabel } from "../lib/presentation";
import type { Decision, DecisionState, Finding } from "../types";
import { FindingCategoryBadges } from "./finding-category-badges";
import { UnsavedChanges } from "./unsaved-changes";

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
    const [comment, setComment] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string>();
    const [saved, setSaved] = useState<Decision>();
    const [changing, setChanging] = useState(false);
    const contentRef = useRef<HTMLDivElement>(null);
    const latest =
        saved && saved.revision > finding.revision
            ? saved
            : finding.decisions.at(0);
    const state = latest?.state ?? finding.state;
    const showDecisionActions = state === "needs_review" || changing;
    const history =
        saved && saved.revision > finding.revision
            ? [saved, ...finding.decisions]
            : finding.decisions;
    useLayoutEffect(() => {
        if (changing && contentRef.current) {
            contentRef.current.scrollTop = contentRef.current.scrollHeight;
        }
    }, [changing]);
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
                    comment: comment.trim() || null,
                    expected_revision: Math.max(
                        finding.revision,
                        saved?.revision ?? 0,
                    ),
                },
            );
            setSaved(result);
            setComment("");
            setChanging(false);
            toast.success(
                decision === "confirmed" ? "Flag confirmed." : "Flag dismissed.",
            );
            onSaved();
        } catch (error_) {
            if (isApiError(error_) && error_.status === 412) {
                setSaved(undefined);
                setChanging(true);
                onReload();
                toast.info(
                    "Decision changed. Review the latest decision; your comment is still here.",
                );
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
            className="h-full"
            size="sm"
        >
            <UnsavedChanges
                dirty={comment.length > 0}
                onDiscard={() => {
                    setComment("");
                }}
                pending={saving}
            />
            <CardHeader className="shrink-0">
                <CardTitle className="text-base!">{finding.title}</CardTitle>
                <FindingCategoryBadges categories={finding.categories} />
            </CardHeader>
            <CardContent
                className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto [scrollbar-gutter:stable]"
                ref={contentRef}
            >
                <CardDescription className="text-base break-words whitespace-pre-wrap">
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
                {history.length > 0 && (
                    <section
                        aria-label="Decision history"
                        className="border-t pt-2"
                    >
                        <ol className="flex flex-col gap-2">
                            {history.map((decision) => (
                                <li key={decision.revision}>
                                    <div className="flex flex-wrap gap-x-1">
                                        <span className="font-medium">
                                            {decisionLabel(decision.state)}
                                        </span>
                                        <span className="text-muted-foreground">
                                            by {decision.reviewer} ·{" "}
                                            {formatTableTimestamp(
                                                decision.created_at,
                                            )}
                                        </span>
                                    </div>
                                    {decision.comment !== null &&
                                        decision.comment !== "" && (
                                            <p className="text-muted-foreground break-words whitespace-pre-wrap">
                                                {decision.comment}
                                            </p>
                                        )}
                                </li>
                            ))}
                        </ol>
                    </section>
                )}
                {showDecisionActions && (
                    <div className="border-t pt-2">
                        <Textarea
                            aria-label="Decision comment (optional)"
                            className="min-h-20 resize-none"
                            disabled={saving}
                            id={`decision-comment-${finding.id}`}
                            maxLength={4000}
                            onChange={(event) => {
                                setComment(event.target.value);
                            }}
                            placeholder="Decision comment (optional)"
                            value={comment}
                        />
                    </div>
                )}
            </CardContent>
            <CardFooter
                className="shrink-0 flex-col gap-2"
                variant="plain"
            >
                <div className="flex gap-2">
                    {showDecisionActions ? (
                        <>
                            <Button
                                aria-busy={saving}
                                disabled={saving}
                                onClick={() => {
                                    void save("confirmed");
                                }}
                                pressMotion={false}
                            >
                                Confirm
                            </Button>
                            <Button
                                aria-busy={saving}
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
