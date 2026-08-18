import { Time } from "@internationalized/date";
import { Button } from "@va/shared/components/ui/button";
import { Calendar } from "@va/shared/components/ui/calendar";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@va/shared/components/ui/popover";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import { cn } from "@va/shared/lib/utils";
import { CalendarIcon } from "lucide-react";
import { type JSX, useEffect, useRef, useState } from "react";
import {
    type DateFieldState,
    DateInput,
    DateSegment,
    I18nProvider,
    Label,
    TimeField,
} from "react-aria-components";

import {
    type CustomTimeRange,
    isTimeRangeValue,
    timeRangeOptions,
    type TimeRangeValue,
} from "../lib/time-range";

const WHEEL_DELTA_THRESHOLD = 40;
const browserDateTimeFormatter = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
});
const browserDateTimeFormatOptions = browserDateTimeFormatter.resolvedOptions();
const BROWSER_LOCALE = browserDateTimeFormatOptions.locale;
const BROWSER_HOUR_CYCLE: 12 | 24 =
    browserDateTimeFormatOptions.hour12 === true ? 12 : 24;
const ENDPOINT_CAPACITY_SAMPLE = new Date(2028, 0, 28, 23, 58);

interface KeyedDateTimePart {
    key: string;
    value: string;
}

const getKeyedDateTimeParts = (date: Date): KeyedDateTimePart[] => {
    const occurrences = new Map<string, number>();
    return browserDateTimeFormatter.formatToParts(date).map((part) => {
        const occurrence = occurrences.get(part.type) ?? 0;
        occurrences.set(part.type, occurrence + 1);
        return {
            key: `${part.type}:${occurrence}`,
            value: part.value,
        };
    });
};

const buildEndpointCapacity = (): Map<string, string[]> => {
    const values = new Map<string, Set<string>>();
    for (let month = 0; month < 12; month += 1) {
        for (let day = 1; day <= 28; day += 27) {
            for (let hour = 0; hour < 24; hour += 1) {
                const sample = new Date(2028, month, day, hour, 58);
                for (const part of getKeyedDateTimeParts(sample)) {
                    const candidates =
                        values.get(part.key) ?? new Set<string>();
                    candidates.add(part.value);
                    values.set(part.key, candidates);
                }
            }
        }
    }
    return new Map(
        [...values].map(([key, candidates]) => [key, [...candidates]]),
    );
};

const ENDPOINT_CAPACITY = buildEndpointCapacity();

interface TimeRangeFilterProps {
    value: TimeRangeValue;
    customRange: CustomTimeRange;
    onCustomRangeChange: (value: CustomTimeRange) => void;
    onChange: (value: TimeRangeValue) => void;
}

interface CustomRangePickerProps {
    initialRange: CustomTimeRange;
    onChange: (value: CustomTimeRange) => void;
}

interface TimeBoundaryInputProps {
    date?: Date;
    isEnd: boolean;
    label: string;
    onChange: (value: Date) => void;
    onCommit: () => void;
}

const RangeEndpoint = ({ date }: { date?: Date }): JSX.Element => {
    const parts = getKeyedDateTimeParts(date ?? ENDPOINT_CAPACITY_SAMPLE);
    return (
        <span className="relative inline-grid auto-cols-max grid-flow-col whitespace-nowrap tabular-nums">
            {parts.map((part) => (
                <span
                    className="grid whitespace-pre"
                    key={part.key}
                >
                    {(ENDPOINT_CAPACITY.get(part.key) ?? []).map(
                        (candidate) => (
                            <span
                                aria-hidden
                                className="invisible col-start-1 row-start-1"
                                key={candidate}
                            >
                                {candidate}
                            </span>
                        ),
                    )}
                    <span
                        className={cn(
                            "col-start-1 row-start-1",
                            !date && "invisible",
                        )}
                    >
                        {part.value}
                    </span>
                </span>
            ))}
            {!date && <span className="absolute start-0">…</span>}
        </span>
    );
};

const RangeLabel = ({ range }: { range: CustomTimeRange }): JSX.Element => {
    if (!range.start) {
        return <>Pick range</>;
    }
    return (
        <span
            aria-hidden
            className="grid min-w-0 grid-cols-[max-content_auto_max-content] items-center gap-1"
        >
            <RangeEndpoint date={range.start} />
            <span>–</span>
            <RangeEndpoint date={range.end} />
        </span>
    );
};

const getDefaultCustomRange = (): { start: Date; end: Date } => {
    const end = new Date();
    end.setHours(23, 59, 59, 999);
    const start = new Date(end);
    start.setDate(end.getDate() - 29);
    start.setHours(0, 0, 0, 0);
    return { start, end };
};

const withDate = (date: Date, timeSource: Date, isEnd: boolean): Date => {
    const result = new Date(date);
    result.setHours(
        timeSource.getHours(),
        timeSource.getMinutes(),
        isEnd ? 59 : 0,
        isEnd ? 999 : 0,
    );
    return result;
};

const ensureOrderedRange = (
    range: CustomTimeRange,
    changedBoundary: "start" | "end",
): CustomTimeRange => {
    if (!range.start || !range.end || range.start <= range.end) {
        return range;
    }
    if (changedBoundary === "start") {
        const end = new Date(range.start);
        end.setSeconds(59, 999);
        return { start: range.start, end };
    }
    const start = new Date(range.end);
    start.setSeconds(0, 0);
    return { start, end: range.end };
};

const WheelAwareDateInput = ({
    onCommit,
    state,
}: {
    onCommit: () => void;
    state: DateFieldState;
}): JSX.Element => {
    const inputRef = useRef<HTMLDivElement>(null);
    const wheelDeltaRef = useRef(0);
    const wheelSegmentRef = useRef<"hour" | "minute" | "dayPeriod" | undefined>(
        undefined,
    );

    useEffect((): (() => void) | undefined => {
        const input = inputRef.current;
        if (!input) {
            return undefined;
        }

        const handleWheel = (event: WheelEvent): void => {
            const focusedElement = document.activeElement;
            if (
                !(focusedElement instanceof HTMLElement) ||
                !input.contains(focusedElement) ||
                event.deltaY === 0
            ) {
                return;
            }
            const segment = focusedElement.dataset.type;
            if (
                segment !== "hour" &&
                segment !== "minute" &&
                segment !== "dayPeriod"
            ) {
                return;
            }

            event.preventDefault();
            if (wheelSegmentRef.current !== segment) {
                wheelDeltaRef.current = 0;
                wheelSegmentRef.current = segment;
            }
            wheelDeltaRef.current += event.deltaY;
            if (Math.abs(wheelDeltaRef.current) < WHEEL_DELTA_THRESHOLD) {
                return;
            }

            if (wheelDeltaRef.current < 0) {
                state.increment(segment);
            } else {
                state.decrement(segment);
            }
            wheelDeltaRef.current = 0;
        };

        const handleFocusOut = (): void => {
            wheelDeltaRef.current = 0;
            wheelSegmentRef.current = undefined;
            queueMicrotask(onCommit);
        };

        input.addEventListener("focusout", handleFocusOut);
        input.addEventListener("wheel", handleWheel, { passive: false });
        return (): void => {
            input.removeEventListener("focusout", handleFocusOut);
            input.removeEventListener("wheel", handleWheel);
        };
    }, [onCommit, state]);

    return (
        <DateInput
            className="border-input focus-within:border-ring focus-within:ring-ring/50 dark:bg-input/30 flex h-8 min-w-0 items-center rounded-lg border bg-transparent px-2.5 text-sm transition-colors outline-none focus-within:ring-3 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50"
            ref={inputRef}
        >
            {(segment) => (
                <DateSegment
                    className={({ isFocused, isPlaceholder, type }) =>
                        cn(
                            "rounded px-0.5 tabular-nums outline-none",
                            type === "literal" && "px-0",
                            isFocused && "bg-accent text-accent-foreground",
                            isPlaceholder && "text-muted-foreground",
                        )
                    }
                    segment={segment}
                />
            )}
        </DateInput>
    );
};

const TimeBoundaryInput = ({
    date,
    isEnd,
    label,
    onChange,
    onCommit,
}: TimeBoundaryInputProps): JSX.Element => {
    const value = date ? new Time(date.getHours(), date.getMinutes()) : null;

    return (
        <I18nProvider locale={BROWSER_LOCALE}>
            <TimeField
                className="flex flex-1 flex-col gap-2"
                granularity="minute"
                hourCycle={BROWSER_HOUR_CYCLE}
                isDisabled={!date}
                onChange={(time) => {
                    if (!date || !time) {
                        return;
                    }
                    const nextDate = new Date(date);
                    nextDate.setHours(
                        time.hour,
                        time.minute,
                        isEnd ? 59 : 0,
                        isEnd ? 999 : 0,
                    );
                    onChange(nextDate);
                }}
                value={value}
            >
                {({ state }) => (
                    <>
                        <Label className="text-sm leading-none font-medium select-none">
                            {label}
                        </Label>
                        <WheelAwareDateInput
                            onCommit={onCommit}
                            state={state}
                        />
                    </>
                )}
            </TimeField>
        </I18nProvider>
    );
};

const CustomRangePicker = ({
    initialRange,
    onChange,
}: CustomRangePickerProps): JSX.Element => {
    const [draftRange, setDraftRange] = useState(initialRange);
    const [open, setOpen] = useState(false);
    const pendingRangeRef = useRef<CustomTimeRange | undefined>(undefined);

    const flushPendingRange = (): void => {
        const pendingRange = pendingRangeRef.current;
        pendingRangeRef.current = undefined;
        if (pendingRange) {
            onChange(pendingRange);
        }
    };

    const applyDateRange = (nextRange: CustomTimeRange): void => {
        setDraftRange(nextRange);
        pendingRangeRef.current = undefined;
        onChange(nextRange);
    };

    const stageTimeRange = (nextRange: CustomTimeRange): void => {
        setDraftRange(nextRange);
        pendingRangeRef.current = nextRange;
    };

    const selectedRange = draftRange.start
        ? { from: draftRange.start, to: draftRange.end }
        : undefined;
    const triggerLabel = draftRange.start
        ? `Select custom range: ${browserDateTimeFormatter.format(
              draftRange.start,
          )} – ${draftRange.end ? browserDateTimeFormatter.format(draftRange.end) : "not selected"}`
        : "Pick custom range";

    return (
        <Popover
            onOpenChange={(nextOpen) => {
                if (!nextOpen) {
                    flushPendingRange();
                }
                setOpen(nextOpen);
            }}
            open={open}
        >
            <PopoverTrigger
                render={
                    <Button
                        aria-label={triggerLabel}
                        className={cn(
                            "w-auto justify-start font-normal",
                            !draftRange.start && "text-muted-foreground",
                        )}
                        variant="outline"
                    >
                        <CalendarIcon data-icon="inline-start" />
                        <RangeLabel range={draftRange} />
                    </Button>
                }
            />
            <PopoverContent
                align="start"
                className="w-auto p-0"
            >
                <Calendar
                    autoFocus
                    captionLayout="dropdown"
                    mode="range"
                    numberOfMonths={1}
                    onSelect={(range) => {
                        const defaults = getDefaultCustomRange();
                        const start = range?.from
                            ? withDate(
                                  range.from,
                                  draftRange.start ?? defaults.start,
                                  false,
                              )
                            : undefined;
                        const end = range?.to
                            ? withDate(
                                  range.to,
                                  draftRange.end ?? defaults.end,
                                  true,
                              )
                            : undefined;
                        applyDateRange(
                            ensureOrderedRange({ start, end }, "start"),
                        );
                    }}
                    selected={selectedRange}
                />
                <div className="flex gap-3 border-t p-3">
                    <TimeBoundaryInput
                        date={draftRange.start}
                        isEnd={false}
                        label="Start time"
                        onChange={(start) => {
                            stageTimeRange(
                                ensureOrderedRange(
                                    { ...draftRange, start },
                                    "start",
                                ),
                            );
                        }}
                        onCommit={flushPendingRange}
                    />
                    <TimeBoundaryInput
                        date={draftRange.end}
                        isEnd
                        label="End time"
                        onChange={(end) => {
                            stageTimeRange(
                                ensureOrderedRange(
                                    { ...draftRange, end },
                                    "end",
                                ),
                            );
                        }}
                        onCommit={flushPendingRange}
                    />
                </div>
            </PopoverContent>
        </Popover>
    );
};

export const TimeRangeFilter = ({
    value,
    customRange,
    onCustomRangeChange,
    onChange,
}: TimeRangeFilterProps): JSX.Element => {
    const selectedTimeRangeLabel =
        timeRangeOptions.find((option) => option.value === value)?.label ??
        "Last 30 days";

    return (
        <div className="flex flex-wrap items-center gap-2">
            <Select
                onValueChange={(next) => {
                    if (next !== null && isTimeRangeValue(next)) {
                        if (
                            next === "custom" &&
                            !customRange.start &&
                            !customRange.end
                        ) {
                            onCustomRangeChange(getDefaultCustomRange());
                        }
                        onChange(next);
                    }
                }}
                value={value}
            >
                <SelectTrigger
                    aria-label="Select time range"
                    className="w-[170px]"
                >
                    <SelectValue>{selectedTimeRangeLabel}</SelectValue>
                </SelectTrigger>
                <SelectContent className="rounded-xl">
                    <SelectGroup>
                        {timeRangeOptions.map((option) => (
                            <SelectItem
                                className="rounded-lg"
                                key={option.value}
                                value={option.value}
                            >
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                </SelectContent>
            </Select>
            {value === "custom" && (
                <CustomRangePicker
                    initialRange={customRange}
                    onChange={onCustomRangeChange}
                />
            )}
        </div>
    );
};
