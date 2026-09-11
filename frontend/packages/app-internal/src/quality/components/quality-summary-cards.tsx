import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    ArrowUpRight,
    CircleX,
    Gauge,
    RotateCcw,
    ShieldAlert,
    ThumbsDown,
    ThumbsUp,
    Timer,
} from "lucide-react";
import type { JSX, ReactNode } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import type {
    QualityFeedbackRating,
    QualityGuardrailStatus,
    QualityMetrics,
} from "../types";

interface ResponsivenessSummaryCardsProps {
    canInspect: boolean;
    onInspect: () => void;
    summary: QualityMetrics;
}

interface FeedbackSummaryCardsProps {
    canInspect: boolean;
    onInspect: (rating?: QualityFeedbackRating) => void;
    summary: QualityMetrics;
}

interface GuardrailSummaryCardsProps {
    canInspect: boolean;
    onInspect: (status?: QualityGuardrailStatus) => void;
    summary: QualityMetrics;
}

interface MetricCardProps {
    description?: string;
    icon: ReactNode;
    inspectLabel?: string;
    onInspect?: () => void;
    title: string;
    value: string;
}

const cardGridClassName =
    "*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs @xl/main:grid-cols-2";

const formatDuration = (value: number | null): string =>
    value === null
        ? "—"
        : `${formatLocaleNumber(value, { maximumFractionDigits: 1 })}s`;

const formatPercent = (value: number | null): string =>
    value === null
        ? "—"
        : formatLocaleNumber(value, {
              maximumFractionDigits: 1,
              style: "percent",
          });

const MetricCard = ({
    description,
    icon,
    inspectLabel,
    onInspect,
    title,
    value,
}: MetricCardProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardDescription>{title}</CardDescription>
            <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                {value}
            </CardTitle>
            <CardAction className="flex items-center gap-2">
                {icon}
                {onInspect !== undefined && inspectLabel !== undefined && (
                    <Button
                        aria-label={inspectLabel}
                        onClick={onInspect}
                        size="icon-sm"
                        title={inspectLabel}
                        variant="ghost"
                    >
                        <ArrowUpRight />
                    </Button>
                )}
            </CardAction>
        </CardHeader>
        {description !== undefined && (
            <CardContent className="text-muted-foreground text-sm">
                {description}
            </CardContent>
        )}
    </Card>
);

export const ResponsivenessSummaryCards = ({
    canInspect,
    onInspect,
    summary,
}: ResponsivenessSummaryCardsProps): JSX.Element => (
    <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Responsiveness</h2>
        <div className={`${cardGridClassName} @4xl/main:grid-cols-3`}>
            <MetricCard
                description={`${formatLocaleNumber(summary.response_samples)} timed responses.`}
                icon={<Timer className="text-muted-foreground size-5" />}
                inspectLabel={canInspect ? "Open slowest responses" : undefined}
                onInspect={canInspect ? onInspect : undefined}
                title="Median response time"
                value={formatDuration(summary.median_response_seconds)}
            />
            <MetricCard
                description={`${formatLocaleNumber(summary.response_samples)} timed responses.`}
                icon={<Gauge className="text-muted-foreground size-5" />}
                inspectLabel={canInspect ? "Open slowest responses" : undefined}
                onInspect={canInspect ? onInspect : undefined}
                title="P95 response time"
                value={formatDuration(summary.p95_response_seconds)}
            />
            <MetricCard
                description={
                    summary.generation_failure_rate === null
                        ? "No tracked generation attempts in this range."
                        : `${formatPercent(summary.generation_failure_rate)} of ${formatLocaleNumber(summary.tracked_generation_attempts)} tracked attempts.`
                }
                icon={<CircleX className="text-destructive size-5" />}
                title="Failed generations"
                value={formatLocaleNumber(summary.failed_generations)}
            />
        </div>
    </section>
);

export const FeedbackSummaryCards = ({
    canInspect,
    onInspect,
    summary,
}: FeedbackSummaryCardsProps): JSX.Element => (
    <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Feedback</h2>
        <div className={`${cardGridClassName} @4xl/main:grid-cols-4`}>
            <MetricCard
                icon={<ThumbsUp className="text-muted-foreground size-5" />}
                inspectLabel={canInspect ? "Open all feedback" : undefined}
                onInspect={
                    canInspect
                        ? (): void => {
                              onInspect();
                          }
                        : undefined
                }
                title="Total ratings"
                value={formatLocaleNumber(summary.ratings)}
            />
            <MetricCard
                icon={<ThumbsUp className="text-muted-foreground size-5" />}
                inspectLabel={canInspect ? "Open thumbs up ratings" : undefined}
                onInspect={
                    canInspect
                        ? (): void => {
                              onInspect("thumbs_up");
                          }
                        : undefined
                }
                title="Thumbs up"
                value={formatLocaleNumber(summary.thumbs_up)}
            />
            <MetricCard
                icon={<ThumbsDown className="text-destructive size-5" />}
                inspectLabel={
                    canInspect ? "Open thumbs down ratings" : undefined
                }
                onInspect={
                    canInspect
                        ? (): void => {
                              onInspect("thumbs_down");
                          }
                        : undefined
                }
                title="Thumbs down"
                value={formatLocaleNumber(summary.thumbs_down)}
            />
            <MetricCard
                description={
                    summary.ratings === 0
                        ? "No matching ratings."
                        : "Share of ratings that are positive."
                }
                icon={<ThumbsUp className="text-muted-foreground size-5" />}
                inspectLabel={canInspect ? "Open all feedback" : undefined}
                onInspect={
                    canInspect
                        ? (): void => {
                              onInspect();
                          }
                        : undefined
                }
                title="Positive rate"
                value={formatPercent(summary.positive_rate)}
            />
        </div>
    </section>
);

export const GuardrailSummaryCards = ({
    canInspect,
    onInspect,
    summary,
}: GuardrailSummaryCardsProps): JSX.Element => (
    <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Guardrails</h2>
        <div className={`${cardGridClassName} @4xl/main:grid-cols-3`}>
            <MetricCard
                description={
                    summary.assistant_responses === 0
                        ? "No matching responses."
                        : summary.retry_affected_rate === null
                          ? "Retry rate unavailable."
                          : `${formatPercent(summary.retry_affected_rate)} of ${formatLocaleNumber(summary.retry_observed_responses)} responses with retry data.`
                }
                icon={<RotateCcw className="text-muted-foreground size-5" />}
                inspectLabel={
                    canInspect
                        ? "Open responses that required retries"
                        : undefined
                }
                onInspect={
                    canInspect
                        ? (): void => {
                              onInspect("retried");
                          }
                        : undefined
                }
                title="Retried responses"
                value={formatLocaleNumber(summary.retry_affected_responses)}
            />
            <MetricCard
                description="Times the chatbot tried again."
                icon={<RotateCcw className="text-muted-foreground size-5" />}
                inspectLabel={
                    canInspect
                        ? "Open responses that required retries"
                        : undefined
                }
                onInspect={
                    canInspect
                        ? (): void => {
                              onInspect("retried");
                          }
                        : undefined
                }
                title="Retry attempts"
                value={formatLocaleNumber(summary.retry_attempts)}
            />
            <MetricCard
                description={
                    summary.blocked_rate === null
                        ? "No matching responses."
                        : `${formatPercent(summary.blocked_rate)} of responses.`
                }
                icon={<ShieldAlert className="text-destructive size-5" />}
                inspectLabel={canInspect ? "Open blocked responses" : undefined}
                onInspect={
                    canInspect
                        ? (): void => {
                              onInspect("blocked");
                          }
                        : undefined
                }
                title="Blocked responses"
                value={formatLocaleNumber(summary.blocked_responses)}
            />
        </div>
    </section>
);
