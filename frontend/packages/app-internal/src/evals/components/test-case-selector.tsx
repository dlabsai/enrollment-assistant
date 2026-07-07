import { Badge } from "@va/shared/components/ui/badge";
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
import { Check, ChevronsUpDown, X } from "lucide-react";
import { type JSX, useMemo, useState } from "react";

import { formatLocaleNumber } from "../../lib/number-format";

interface TestCaseSelectorProps {
    allowCustomValues?: boolean;
    availableLabel?: string;
    emptyLabel: string;
    options: string[];
    placeholder: string;
    selectedValues: string[];
    triggerLabel?: string;
    onSelectedValuesChange: (values: string[]) => void;
}

const normalizeSearch = (value: string): string => value.trim();

export const TestCaseSelector = ({
    allowCustomValues = false,
    availableLabel = "available",
    emptyLabel,
    options,
    placeholder,
    selectedValues,
    triggerLabel,
    onSelectedValuesChange,
}: TestCaseSelectorProps): JSX.Element => {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState("");
    const selectedSet = useMemo(() => new Set(selectedValues), [selectedValues]);
    const normalizedSearch = normalizeSearch(search);
    const filteredOptions = useMemo(() => {
        const query = normalizedSearch.toLowerCase();
        if (query === "") {
            return options;
        }
        return options.filter((caseId) => caseId.toLowerCase().includes(query));
    }, [normalizedSearch, options]);
    const customValues = useMemo(() => {
        if (!allowCustomValues || normalizedSearch === "") {
            return [];
        }
        const values = normalizedSearch
            .split(",")
            .map((entry) => entry.trim())
            .filter((entry) => entry !== "");
        return values.filter(
            (entry) => !selectedSet.has(entry) && !options.includes(entry),
        );
    }, [allowCustomValues, normalizedSearch, options, selectedSet]);

    const toggleValue = (caseId: string): void => {
        onSelectedValuesChange(
            selectedSet.has(caseId)
                ? selectedValues.filter((entry) => entry !== caseId)
                : [...selectedValues, caseId],
        );
    };
    const addValues = (caseIds: string[]): void => {
        const seen = new Set(selectedValues);
        const next = [...selectedValues];
        for (const caseId of caseIds) {
            const trimmed = caseId.trim();
            if (trimmed !== "" && !seen.has(trimmed)) {
                seen.add(trimmed);
                next.push(trimmed);
            }
        }
        onSelectedValuesChange(next);
    };
    const selectAllOptions = (): void => {
        const extras = selectedValues.filter((entry) => !options.includes(entry));
        onSelectedValuesChange([...extras, ...options]);
    };
    const removeValue = (caseId: string): void => {
        onSelectedValuesChange(selectedValues.filter((entry) => entry !== caseId));
    };
    const label =
        triggerLabel ??
        (selectedValues.length === 0
            ? "All test cases"
            : `${formatLocaleNumber(selectedValues.length)} selected`);

    return (
        <div className="flex flex-col gap-1">
            <Popover
                onOpenChange={(nextOpen) => {
                    setOpen(nextOpen);
                    if (!nextOpen) {
                        setSearch("");
                    }
                }}
                open={open}
            >
                <PopoverTrigger
                    render={
                        <Button
                            aria-expanded={open}
                            className="h-9 justify-between"
                            role="combobox"
                            type="button"
                            variant="outline"
                        >
                            <span className="truncate">{label}</span>
                            <ChevronsUpDown className="text-muted-foreground size-4" />
                        </Button>
                    }
                />
                <PopoverContent
                    align="start"
                    className="w-[340px] p-0"
                >
                    <Command shouldFilter={false}>
                        <CommandInput
                            onValueChange={setSearch}
                            placeholder={placeholder}
                            value={search}
                        />
                        <div className="text-muted-foreground flex items-center justify-between gap-2 border-b px-3 py-2 text-xs">
                            <span>
                                {formatLocaleNumber(options.length)} {availableLabel}
                            </span>
                            <div className="flex items-center gap-2">
                                <Button
                                    disabled={options.length === 0}
                                    onClick={selectAllOptions}
                                    size="sm"
                                    type="button"
                                    variant="ghost"
                                >
                                    Select all
                                </Button>
                                <Button
                                    disabled={selectedValues.length === 0}
                                    onClick={() => {
                                        onSelectedValuesChange([]);
                                    }}
                                    size="sm"
                                    type="button"
                                    variant="ghost"
                                >
                                    Clear
                                </Button>
                            </div>
                        </div>
                        <CommandList>
                            <CommandEmpty>{emptyLabel}</CommandEmpty>
                            <CommandGroup>
                                {filteredOptions.map((caseId) => {
                                    const isSelected = selectedSet.has(caseId);
                                    return (
                                        <CommandItem
                                            key={caseId}
                                            onSelect={() => {
                                                toggleValue(caseId);
                                            }}
                                            value={caseId}
                                        >
                                            <Check
                                                className={`size-4 ${isSelected ? "opacity-100" : "opacity-0"}`}
                                            />
                                            <span className="truncate">{caseId}</span>
                                        </CommandItem>
                                    );
                                })}
                                {customValues.length > 0 && (
                                    <CommandItem
                                        onSelect={() => {
                                            addValues(customValues);
                                            setSearch("");
                                        }}
                                        value={normalizedSearch}
                                    >
                                        <Check className="size-4 opacity-0" />
                                        <span>Add {normalizedSearch}</span>
                                    </CommandItem>
                                )}
                            </CommandGroup>
                        </CommandList>
                    </Command>
                </PopoverContent>
            </Popover>
            {selectedValues.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-2">
                    {selectedValues.map((caseId) => (
                        <Badge
                            className="gap-1"
                            key={caseId}
                            variant="secondary"
                        >
                            <span>{caseId}</span>
                            <button
                                aria-label={`Remove ${caseId}`}
                                className="text-muted-foreground hover:text-foreground"
                                onClick={(event) => {
                                    event.stopPropagation();
                                    removeValue(caseId);
                                }}
                                type="button"
                            >
                                <X className="size-3" />
                            </button>
                        </Badge>
                    ))}
                </div>
            )}
        </div>
    );
};
