import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@va/shared/components/ui/dialog";
import { Spinner } from "@va/shared/components/ui/spinner";
import { ScanSearch } from "lucide-react";
import { type JSX, useCallback, useMemo, useState } from "react";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
import { InlineError } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import { formatTableTimestamp } from "../../lib/date-format";
import { formatLocaleNumber as number } from "../../lib/number-format";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import { useComplianceData } from "../hooks/use-compliance-data";
import type { Period, Preview, ScreeningDetail } from "../types";

export const NewScreening = ({
    onStarted,
}: {
    onStarted: (id: string) => void;
}): JSX.Element => {
    const api = useAuthenticatedApi();
    const { user } = useAuth();
    const canEdit = hasPermission(user, "edit_compliance_instructions");
    const [open, setOpen] = useState(false);
    const [range, setRange] = useState<{
        value: TimeRangeValue;
        custom: CustomTimeRange;
        reference: Date;
    }>(() => ({ value: "7d", custom: {}, reference: new Date() }));
    const [requestId, setRequestId] = useState(() => crypto.randomUUID());
    const [starting, setStarting] = useState(false);
    const [showStarting, setShowStarting] = useState(false);
    const [confirmingOverlap, setConfirmingOverlap] = useState(false);
    const [startError, setStartError] = useState<string>();
    const period = useMemo<Period | undefined>(() => {
        const resolved = getTimeRangeQueryParams(
            range.value,
            range.reference,
            range.custom,
        );
        if (
            range.value === "custom" &&
            (resolved.start === undefined || resolved.end === undefined)
        ) {
            return void 0;
        }
        return {
            start: resolved.start ?? new Date(0).toISOString(),
            end: resolved.end ?? range.reference.toISOString(),
        };
    }, [range]);
    const previewActive = open;
    const load = useCallback(
        async (signal: AbortSignal): Promise<Preview | undefined> => {
            if (!previewActive || !period) {
                return undefined;
            }
            return api.post<Preview>("/compliance/screenings/preview", period, {
                signal,
            });
        },
        [api, period, previewActive],
    );
    const {
        data,
        loading,
        error,
        refresh: handleRefresh,
    } = useComplianceData<Preview | undefined>({
        load,
        enabled: previewActive && period !== undefined,
        poll: false,
        retainPreviousData: true,
        errorMessage: "Could not count the chats. Please try again.",
    });
    const start = async (acknowledgeOverlap: boolean): Promise<void> => {
        if (!period || !data?.instructions || loading) {
            return;
        }
        setStarting(true);
        setStartError(undefined);
        const loadingTimer = window.setTimeout(() => {
            setShowStarting(true);
        }, 300);
        try {
            const screening = await api.post<ScreeningDetail>("/compliance/screenings", {
                ...period,
                id: requestId,
                instructions_version_id: data.instructions.id,
                acknowledge_overlap: acknowledgeOverlap,
            });
            setConfirmingOverlap(false);
            setOpen(false);
            onStarted(screening.id);
        } catch (error_) {
            setStartError(
                error_ instanceof Error
                    ? error_.message
                    : "Could not start the screening. Please try again.",
            );
            handleRefresh();
        } finally {
            window.clearTimeout(loadingTimer);
            setShowStarting(false);
            setStarting(false);
        }
    };
    const changeRange = (update: {
        value?: TimeRangeValue;
        custom?: CustomTimeRange;
    }): void => {
        setRange((previous) => ({
            ...previous,
            ...update,
            reference: new Date(),
        }));
        setRequestId(crypto.randomUUID());
        setStartError(undefined);
    };
    const previewScope = data
        ? `${number(data.messages)} assistant message${data.messages === 1 ? "" : "s"} from ${number(data.conversations)} chat${data.conversations === 1 ? "" : "s"}`
        : "— assistant messages from — chats";
    const unavailable =
        loading ||
        starting ||
        error !== undefined ||
        !period ||
        !data?.instructions ||
        !data.worker_enabled ||
        data.messages === 0 ||
        data.messages > data.max_messages;
    const availability = period
        ? data?.instructions === null
            ? canEdit
                ? "Add your team's instructions before the first screening."
                : "Your instruction owner needs to add instructions before screenings can start."
            : data && !data.worker_enabled
              ? "Screening is temporarily unavailable. Previous results are still accessible."
              : data && data.messages > data.max_messages
                ? `Choose a shorter period — up to ${number(data.max_messages)} assistant messages per screening.`
                : ""
        : "Choose a start and end date.";
    return (
        <Dialog
            onOpenChange={(nextOpen) => {
                if (!starting || nextOpen) {
                    setOpen(nextOpen);
                    if (nextOpen) {
                        setRange((previous) => ({
                            ...previous,
                            reference: new Date(),
                        }));
                        setRequestId(crypto.randomUUID());
                    } else {
                        setConfirmingOverlap(false);
                        setStartError(undefined);
                    }
                }
            }}
            open={open}
        >
            <DialogTrigger render={<Button />}>
                <ScanSearch data-icon="inline-start" />
                New
            </DialogTrigger>
            <DialogContent
                className="sm:max-w-xl"
                showCloseButton={!starting}
            >
                <DialogHeader>
                    <DialogTitle>
                        {confirmingOverlap
                            ? "Screen this period again?"
                            : "New screening"}
                    </DialogTitle>
                    {confirmingOverlap && (
                        <DialogDescription>
                            Some of these dates are included in previous
                            screenings. This will create a separate screening;
                            earlier decisions stay unchanged.
                        </DialogDescription>
                    )}
                </DialogHeader>
                {confirmingOverlap ? (
                    <div className="flex max-h-64 flex-col gap-2 overflow-auto">
                        {data?.overlaps.map((overlap) => (
                            <Button
                                key={overlap.id}
                                onClick={() => {
                                    setConfirmingOverlap(false);
                                    setOpen(false);
                                    onStarted(overlap.id);
                                }}
                                variant="outline"
                            >
                                Open screening from{" "}
                                {formatTableTimestamp(overlap.created_at)}
                            </Button>
                        ))}
                    </div>
                ) : (
                    <div
                        aria-label="Start screening"
                        className="flex flex-col gap-3"
                    >
                        <div className="flex flex-wrap items-center gap-3">
                            <TimeRangeFilter
                                compact
                                customRange={range.custom}
                                onChange={(value) => {
                                    changeRange({ value });
                                }}
                                onCustomRangeChange={(custom) => {
                                    changeRange({ custom });
                                }}
                                value={range.value}
                            />
                            <span
                                aria-busy={loading}
                                className="text-muted-foreground text-sm tabular-nums"
                                role="status"
                            >
                                {previewScope}
                            </span>
                        </div>
                        {availability !== "" && (
                            <p className="text-muted-foreground text-sm">
                                {availability}
                            </p>
                        )}
                        {error !== undefined && (
                            <InlineError
                                message={error}
                                onRetry={handleRefresh}
                            />
                        )}
                    </div>
                )}
                {startError !== undefined && (
                    <Alert variant="destructive">
                        <AlertDescription>{startError}</AlertDescription>
                    </Alert>
                )}
                <DialogFooter>
                    {confirmingOverlap ? (
                        <>
                            <Button
                                disabled={starting}
                                onClick={() => {
                                    setConfirmingOverlap(false);
                                }}
                                variant="outline"
                            >
                                Back
                            </Button>
                            <Button
                                aria-busy={starting}
                                disabled={starting}
                                onClick={() => {
                                    void start(true);
                                }}
                            >
                                {showStarting && (
                                    <Spinner data-icon="inline-start" />
                                )}
                                {showStarting
                                    ? "Starting screening…"
                                    : "Start separate screening"}
                            </Button>
                        </>
                    ) : (
                        <Button
                            aria-busy={starting}
                            aria-disabled={unavailable}
                            disabled={unavailable}
                            onClick={() => {
                                if (loading) {
                                    return;
                                }
                                if (data && data.overlaps.length > 0) {
                                    setConfirmingOverlap(true);
                                } else {
                                    void start(false);
                                }
                            }}
                        >
                            {showStarting ? (
                                <Spinner data-icon="inline-start" />
                            ) : (
                                <ScanSearch data-icon="inline-start" />
                            )}
                            {showStarting
                                ? "Starting screening…"
                                : "Start screening"}
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
