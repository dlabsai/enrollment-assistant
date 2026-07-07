import { Button } from "@va/shared/components/ui/button";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@va/shared/components/ui/command";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@va/shared/components/ui/popover";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import { Check, ChevronsUpDown, Filter, RefreshCw } from "lucide-react";
import { type JSX, useEffect, useMemo, useState } from "react";

import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { LoadingState, PageError } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import { formatLocaleNumber } from "../../lib/number-format";
import {
    type CustomTimeRange,
    isTimeRangeValue,
    type TimeRangeValue,
} from "../../lib/time-range";
import { useUsageData } from "../hooks/use-usage-data";
import { CostChart } from "./cost-chart";
import { EmbeddingCostChart } from "./embedding-cost-chart";
import { EmbeddingUsageChart } from "./embedding-usage-chart";
import { ModelBreakdown } from "./model-breakdown";
import { UsageChart } from "./usage-chart";
import { EmbeddingSummaryCards, LlmSummaryCards } from "./usage-summary-cards";
import { UsageTable } from "./usage-table";

const platformOptions = [
    { label: "All platforms", value: "both" },
    { label: "Internal", value: "internal" },
    { label: "Public", value: "public" },
] as const;

const providerFilterOptions = ["openrouter", "openai", "azure"] as const;
const providerFilterOptionsSet = new Set<string>(providerFilterOptions);

const usageFilterStorageKey = "internal-usage-filters";

type PlatformFilter = (typeof platformOptions)[number]["value"];
type ProviderFilter = (typeof providerFilterOptions)[number];

interface StoredUsageFilters {
    platform?: PlatformFilter;
    timeRange?: TimeRangeValue;
    customRange?: {
        start?: string;
        end?: string;
    };
    modelFilters?: string[];
}

const isPlatformFilter = (value: string): value is PlatformFilter =>
    platformOptions.some((option) => option.value === value);

const isProviderFilter = (value: string): value is ProviderFilter =>
    providerFilterOptionsSet.has(value);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

const parseStoredStringArray = (value: unknown): string[] | undefined => {
    if (!Array.isArray(value)) {
        return undefined;
    }
    return value.filter(
        (entry): entry is string => typeof entry === "string" && entry !== "",
    );
};

const parseStoredDate = (value?: string): Date | undefined => {
    if (value === undefined || value === "") {
        return undefined;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

const parseStoredCustomRange = (
    range?: StoredUsageFilters["customRange"],
): CustomTimeRange => ({
    start: parseStoredDate(range?.start),
    end: parseStoredDate(range?.end),
});

const parseStoredUsageFilters = (
    value: string,
): StoredUsageFilters | undefined => {
    try {
        const parsed: unknown = JSON.parse(value);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const customRangeValue = isRecord(parsed.customRange)
            ? parsed.customRange
            : undefined;
        const platformValue =
            typeof parsed.platform === "string" &&
            isPlatformFilter(parsed.platform)
                ? parsed.platform
                : undefined;
        const timeRangeValue =
            typeof parsed.timeRange === "string" &&
            isTimeRangeValue(parsed.timeRange)
                ? parsed.timeRange
                : undefined;
        const modelFiltersValue = parseStoredStringArray(parsed.modelFilters);
        return {
            platform: platformValue,
            timeRange: timeRangeValue,
            customRange: {
                start:
                    typeof customRangeValue?.start === "string"
                        ? customRangeValue.start
                        : undefined,
                end:
                    typeof customRangeValue?.end === "string"
                        ? customRangeValue.end
                        : undefined,
            },
            modelFilters: modelFiltersValue,
        };
    } catch {
        return undefined;
    }
};

const getStoredUsageFilters = (): StoredUsageFilters | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const stored = window.localStorage.getItem(usageFilterStorageKey);
    if (stored === null || stored === "") {
        return undefined;
    }
    return parseStoredUsageFilters(stored);
};

export const UsagePage = (): JSX.Element => {
    const storedFilters = useMemo(() => getStoredUsageFilters(), []);
    const [selectedPlatform, setSelectedPlatform] = useState<PlatformFilter>(
        () => {
            const storedPlatform = storedFilters?.platform;
            if (storedPlatform !== undefined) {
                return storedPlatform;
            }
            return "both";
        },
    );
    const [timeRange, setTimeRange] = useState<TimeRangeValue>(() => {
        const storedTimeRange = storedFilters?.timeRange;
        if (storedTimeRange !== undefined) {
            return storedTimeRange;
        }
        return "30d";
    });
    const [customRange, setCustomRange] = useState<CustomTimeRange>(() =>
        parseStoredCustomRange(storedFilters?.customRange),
    );
    const [modelFilters, setModelFilters] = useState<string[]>(
        () => storedFilters?.modelFilters ?? [],
    );
    const [modelFilterOpen, setModelFilterOpen] = useState(false);
    const [modelFilterSearch, setModelFilterSearch] = useState("");
    const [referenceDate, setReferenceDate] = useState(() => new Date());

    const {
        summary,
        dailyData,
        modelData,
        latestTraces,
        loading,
        hasLoaded,
        error,
        refresh,
    } = useUsageData({
        platform: selectedPlatform,
        timeRange,
        customRange,
        modelFilters,
        referenceDate,
    });

    const modelFilterLabel = useMemo(() => {
        if (modelFilters.length === 0) {
            return "All models";
        }
        if (modelFilters.length === 1) {
            return modelFilters[0];
        }
        return `${formatLocaleNumber(modelFilters.length)} selected`;
    }, [modelFilters]);

    const modelOptions = useMemo(() => {
        const uniqueModels = new Set<string>();
        for (const entry of modelData) {
            uniqueModels.add(entry.model);
        }
        return [...uniqueModels].toSorted((first, second) =>
            first.localeCompare(second),
        );
    }, [modelData]);

    const availableProviderFilters = useMemo(() => {
        const providers = new Set<string>();
        for (const model of modelOptions) {
            const provider = model.split(":")[0] ?? model;
            if (isProviderFilter(provider)) {
                providers.add(provider);
            }
        }
        for (const selected of modelFilters) {
            if (isProviderFilter(selected)) {
                providers.add(selected);
            }
        }
        return providerFilterOptions.filter((provider) =>
            providers.has(provider),
        );
    }, [modelFilters, modelOptions]);

    const toggleModelFilter = (value: string): void => {
        setModelFilters((current) =>
            current.includes(value)
                ? current.filter((item) => item !== value)
                : [...current, value],
        );
    };

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        const payload: StoredUsageFilters = {
            platform: selectedPlatform,
            timeRange,
            customRange: {
                start: customRange.start?.toISOString(),
                end: customRange.end?.toISOString(),
            },
            modelFilters,
        };
        window.localStorage.setItem(
            usageFilterStorageKey,
            JSON.stringify(payload),
        );
    }, [customRange, modelFilters, selectedPlatform, timeRange]);

    if (loading && !hasLoaded) {
        return <LoadingState />;
    }

    if (error !== undefined) {
        return (
            <PageError
                message={error}
                onRetry={() => void refresh()}
            />
        );
    }

    return (
        <PageShell variant="dashboard">
            <PageHeader title="Usage">
                <PageHeaderGroup>
                    <ToggleGroup
                        aria-label="Platform"
                        onValueChange={(value) => {
                            const [nextValue] = value;
                            const next = isPlatformFilter(nextValue)
                                ? nextValue
                                : "both";
                            setSelectedPlatform(next);
                        }}
                        value={[selectedPlatform]}
                        variant="outline"
                    >
                        {platformOptions.map((option) => (
                            <ToggleGroupItem
                                key={option.value}
                                value={option.value}
                            >
                                {option.label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </PageHeaderGroup>
                <PageHeaderGroup>
                    <TimeRangeFilter
                        customRange={customRange}
                        onChange={(value) => {
                            setTimeRange(value);
                            setReferenceDate(new Date());
                        }}
                        onCustomRangeChange={(value) => {
                            setCustomRange(value);
                            setReferenceDate(new Date());
                        }}
                        value={timeRange}
                    />
                </PageHeaderGroup>
                <PageHeaderGroup>
                    <Popover
                        onOpenChange={(open) => {
                            setModelFilterOpen(open);
                            if (!open) {
                                setModelFilterSearch("");
                            }
                        }}
                        open={modelFilterOpen}
                    >
                        <PopoverTrigger
                            render={
                                <Button
                                    aria-expanded={modelFilterOpen}
                                    className="max-w-[240px] justify-between"
                                    role="combobox"
                                    type="button"
                                    variant="outline"
                                >
                                    <span className="truncate">
                                        {modelFilterLabel}
                                    </span>
                                    <ChevronsUpDown className="text-muted-foreground" />
                                </Button>
                            }
                        />
                        <PopoverContent
                            align="start"
                            className="w-[320px] p-0"
                        >
                            <Command>
                                <CommandInput
                                    onValueChange={setModelFilterSearch}
                                    placeholder="Filter models..."
                                    value={modelFilterSearch}
                                />
                                <div className="text-muted-foreground flex items-center justify-between gap-2 border-b px-3 py-2 text-xs">
                                    <span>
                                        {formatLocaleNumber(
                                            modelOptions.length,
                                        )}{" "}
                                        models
                                    </span>
                                    <Button
                                        disabled={modelFilters.length === 0}
                                        onClick={() => {
                                            setModelFilters([]);
                                        }}
                                        size="sm"
                                        type="button"
                                        variant="ghost"
                                    >
                                        Clear
                                    </Button>
                                </div>
                                <CommandList>
                                    <CommandEmpty>
                                        No models found.
                                    </CommandEmpty>
                                    {availableProviderFilters.length > 0 && (
                                        <CommandGroup heading="Providers">
                                            {availableProviderFilters.map(
                                                (provider) => {
                                                    const isSelected =
                                                        modelFilters.includes(
                                                            provider,
                                                        );

                                                    return (
                                                        <CommandItem
                                                            key={provider}
                                                            onSelect={() => {
                                                                toggleModelFilter(
                                                                    provider,
                                                                );
                                                            }}
                                                            value={provider}
                                                        >
                                                            <Check
                                                                className={
                                                                    isSelected
                                                                        ? "opacity-100"
                                                                        : "opacity-0"
                                                                }
                                                            />
                                                            <span className="truncate">
                                                                {provider}
                                                            </span>
                                                        </CommandItem>
                                                    );
                                                },
                                            )}
                                        </CommandGroup>
                                    )}
                                    {modelOptions.length > 0 && (
                                        <CommandGroup heading="Models">
                                            {modelOptions.map((model) => {
                                                const isSelected =
                                                    modelFilters.includes(
                                                        model,
                                                    );

                                                return (
                                                    <CommandItem
                                                        key={model}
                                                        onSelect={() => {
                                                            toggleModelFilter(
                                                                model,
                                                            );
                                                        }}
                                                        value={model}
                                                    >
                                                        <Check
                                                            className={
                                                                isSelected
                                                                    ? "opacity-100"
                                                                    : "opacity-0"
                                                            }
                                                        />
                                                        <span className="truncate">
                                                            {model}
                                                        </span>
                                                    </CommandItem>
                                                );
                                            })}
                                        </CommandGroup>
                                    )}
                                </CommandList>
                            </Command>
                        </PopoverContent>
                    </Popover>
                </PageHeaderGroup>
                <Button
                    onClick={() => {
                        setSelectedPlatform("both");
                        setTimeRange("30d");
                        setCustomRange({});
                        setModelFilters([]);
                        setReferenceDate(new Date());
                    }}
                    variant="outline"
                >
                    <Filter data-icon="inline-start" />
                    Clear
                </Button>
                <Button
                    onClick={() => void refresh()}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
                <div className="flex flex-col gap-4">
                    <LlmSummaryCards summary={summary} />
                    <UsageChart
                        data={dailyData}
                        timeRange={timeRange}
                    />
                    <CostChart
                        data={dailyData}
                        timeRange={timeRange}
                    />
                </div>
                <div className="flex flex-col gap-4">
                    <EmbeddingSummaryCards summary={summary} />
                    <EmbeddingUsageChart
                        data={dailyData}
                        timeRange={timeRange}
                    />
                    <EmbeddingCostChart
                        data={dailyData}
                        timeRange={timeRange}
                    />
                </div>
                <div className="@3xl/main:col-span-2">
                    <ModelBreakdown data={modelData} />
                </div>
            </PageSection>

            <PageSection>
                <UsageTable traces={latestTraces} />
            </PageSection>
        </PageShell>
    );
};
