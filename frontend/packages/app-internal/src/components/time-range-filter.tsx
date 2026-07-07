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
import type { JSX } from "react";

import {
    type CustomTimeRange,
    isTimeRangeValue,
    timeRangeOptions,
    type TimeRangeValue,
} from "../lib/time-range";

interface TimeRangeFilterProps {
    value: TimeRangeValue;
    customRange: CustomTimeRange;
    onCustomRangeChange: (value: CustomTimeRange) => void;
    onChange: (value: TimeRangeValue) => void;
}

const formatRangeDate = (date: Date): string =>
    date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
    });

const formatRangeLabel = (customRange: CustomTimeRange): string => {
    if (customRange.start && customRange.end) {
        return `${formatRangeDate(customRange.start)} – ${formatRangeDate(
            customRange.end,
        )}`;
    }
    if (customRange.start) {
        return `${formatRangeDate(customRange.start)} – …`;
    }
    return "Pick range";
};

const getDefaultCustomRange = (): CustomTimeRange => {
    const end = new Date();
    end.setHours(23, 59, 59, 999);
    const start = new Date(end);
    start.setDate(end.getDate() - 29);
    start.setHours(0, 0, 0, 0);
    return { start, end };
};

export const TimeRangeFilter = ({
    value,
    customRange,
    onCustomRangeChange,
    onChange,
}: TimeRangeFilterProps): JSX.Element => {
    const selectedRange = customRange.start
        ? { from: customRange.start, to: customRange.end }
        : undefined;
    const rangeLabel = formatRangeLabel(customRange);
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
                <Popover>
                    <PopoverTrigger
                        render={
                            <Button
                                className={cn(
                                    "w-auto justify-start font-normal",
                                    !customRange.start &&
                                        "text-muted-foreground",
                                )}
                                variant="outline"
                            >
                                <CalendarIcon data-icon="inline-start" />
                                <span className="whitespace-nowrap">
                                    {rangeLabel}
                                </span>
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
                                onCustomRangeChange({
                                    start: range?.from,
                                    end: range?.to,
                                });
                            }}
                            selected={selectedRange}
                        />
                    </PopoverContent>
                </Popover>
            )}
        </div>
    );
};
