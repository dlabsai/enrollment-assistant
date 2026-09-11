import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { type JSX, useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { PageHeader } from "../../components/page-header";
import { PageSection } from "../../components/page-shell";
import { InlineError, LoadingState } from "../../components/page-state";
import { formatTableTimestamp } from "../../lib/date-format";
import { useComplianceData } from "../hooks/use-compliance-data";
import type { FlagDetail, FlagSummary } from "../types";
import { ConversationTranscript } from "./conversation-transcript";
import { FindingCard } from "./finding-card";

export const FlagReview = ({
    screeningId,
    flagId,
    rows,
    loadingRows,
    notice,
    onBack,
    onSelect,
    onSaved,
}: {
    screeningId: string;
    flagId: string;
    rows: FlagSummary[];
    loadingRows: boolean;
    notice: JSX.Element | undefined;
    onBack: () => void;
    onSelect: (id: string) => void;
    onSaved: () => void;
}): JSX.Element => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal) =>
            api.get<FlagDetail>(
                `/compliance/screenings/${screeningId}/flags/${flagId}`,
                { signal },
            ),
        [api, screeningId, flagId],
    );
    const {
        data,
        error,
        loading,
        refresh: handleRefresh,
    } = useComplianceData({
        load,
        errorMessage: "Could not load this flag.",
        retainPreviousData: true,
    });
    const selectedIndex = rows.findIndex((candidate) => candidate.id === flagId);
    const previous = selectedIndex > 0 ? rows.at(selectedIndex - 1) : undefined;
    const next = selectedIndex === -1 ? undefined : rows.at(selectedIndex + 1);
    const onDecisionSaved = (): void => {
        handleRefresh();
        onSaved();
    };
    const flag = data?.flag ?? null;
    const previousAction = (
        <Button
            aria-label="Previous flag"
            disabled={previous === undefined || loading || loadingRows}
            onClick={() => {
                if (previous) {
                    onSelect(previous.id);
                }
            }}
            variant="outline"
        >
            <ArrowLeft data-icon="inline-start" />
            Previous
        </Button>
    );
    const nextAction = (
        <Button
            aria-label="Next flag"
            disabled={next === undefined || loading || loadingRows}
            onClick={() => {
                if (next) {
                    onSelect(next.id);
                }
            }}
            variant="outline"
        >
            Next
            <ArrowRight data-icon="inline-end" />
        </Button>
    );
    return (
        <>
            <PageHeader
                title="Review flag"
                titleAddon={
                    <Button
                        onClick={onBack}
                        variant="outline"
                    >
                        <ArrowLeft data-icon="inline-start" />
                        Back to screening
                    </Button>
                }
            />
            <PageSection className="flex min-h-0 w-full flex-1 flex-col gap-4">
                {notice}
                {error !== undefined && (
                    <InlineError
                        message={error}
                        onRetry={handleRefresh}
                    />
                )}
                {loading && data === undefined ? (
                    <LoadingState className="min-h-48" />
                ) : (
                    data && (
                        <section
                            aria-busy={loading}
                            aria-label="Flag review"
                            className="flex min-h-0 flex-1 flex-col overflow-hidden"
                            inert={loading}
                        >
                            {data.transcript.length > 0 && (
                                <section
                                    aria-label="Chat"
                                    className="min-h-0 min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]"
                                >
                                    <ConversationTranscript
                                        evidence={flag?.evidence}
                                        key={`${data.message_id}:${flag?.id ?? "unavailable"}`}
                                        messages={data.transcript}
                                        targetId={data.message_id}
                                    />
                                </section>
                            )}
                            <section
                                aria-label={flag === null ? "Unavailable flag" : "Flag"}
                                className="w-full shrink-0 overflow-y-auto px-4 py-3 [scrollbar-gutter:stable]"
                            >
                                <div className="mx-auto max-w-3xl">
                                    {flag === null ? (
                                        <Card
                                            className="h-48"
                                            size="sm"
                                        >
                                            <CardHeader className="min-h-0 flex-1 overflow-y-auto">
                                                <CardTitle>Flag unavailable</CardTitle>
                                                <CardDescription>
                                                    Chat: {data.chat} ·{" "}
                                                    {formatTableTimestamp(
                                                        data.message_at,
                                                    )}
                                                </CardDescription>
                                                <Alert variant="destructive">
                                                    <AlertDescription>
                                                        {data.error ??
                                                            "This flag is no longer available."}
                                                    </AlertDescription>
                                                </Alert>
                                            </CardHeader>
                                            <CardFooter
                                                className="shrink-0 justify-center gap-2"
                                                variant="plain"
                                            >
                                                {previousAction}
                                                {nextAction}
                                            </CardFooter>
                                        </Card>
                                    ) : (
                                        <FindingCard
                                            finding={flag}
                                            key={flag.id}
                                            nextAction={nextAction}
                                            onReload={handleRefresh}
                                            onSaved={onDecisionSaved}
                                            previousAction={previousAction}
                                        />
                                    )}
                                </div>
                            </section>
                        </section>
                    )
                )}
            </PageSection>
        </>
    );
};
