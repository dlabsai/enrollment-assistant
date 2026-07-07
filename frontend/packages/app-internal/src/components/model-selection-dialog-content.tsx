import { Button } from "@va/shared/components/ui/button";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
} from "@va/shared/components/ui/command";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import { Input } from "@va/shared/components/ui/input";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@va/shared/components/ui/tabs";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { cn } from "@va/shared/lib/utils";
import { Check, RotateCcw, Star, Trash2 } from "lucide-react";
import type { ComponentPropsWithoutRef, JSX, ReactNode } from "react";

interface ModelSelectionDialogContentProps<TTarget extends string> {
    dialogContentProps?: ComponentPropsWithoutRef<typeof DialogContent>;
    title?: string;
    defaultPresetValue: string;
    presetSelectValue: string;
    presets: { name: string }[];
    onPresetSelect: (value: string) => void;
    onRequestDeletePreset: (name: string) => void;
    deletePresetOpen: boolean;
    deletePresetName?: string;
    onDeletePresetOpenChange: (open: boolean) => void;
    onDeletePresetCancel: () => void;
    onDeletePresetConfirm: () => void;
    presetName: string;
    onPresetNameChange: (value: string) => void;
    onSavePreset: () => void;
    isSaveDisabled: boolean;
    tabs: { value: TTarget; label: string }[];
    modelTarget: TTarget;
    onModelTargetChange: (value: TTarget) => void;
    currentTargetValue: string;
    onResetCurrentTarget: () => void;
    resetButtonAriaLabel: string;
    resetTooltipLabel?: string;
    extraSection?: ReactNode;
    commandValue: string;
    onCommandValueChange: (value: string) => void;
    onCommandReset: () => void;
    modelsLoading: boolean;
    modelsError?: string;
    favoriteModels: string[];
    groupedModels: { provider: string; models: string[] }[];
    favoriteModelSet: Set<string>;
    onSelectModel: (value: string) => void;
    onToggleFavorite: (value: string) => void;
}

export const ModelSelectionDialogContent = <TTarget extends string>({
    dialogContentProps,
    title = "Model selection",
    defaultPresetValue,
    presetSelectValue,
    presets,
    onPresetSelect,
    onRequestDeletePreset,
    deletePresetOpen,
    deletePresetName,
    onDeletePresetOpenChange,
    onDeletePresetCancel,
    onDeletePresetConfirm,
    presetName,
    onPresetNameChange,
    onSavePreset,
    isSaveDisabled,
    tabs,
    modelTarget,
    onModelTargetChange,
    currentTargetValue,
    onResetCurrentTarget,
    resetButtonAriaLabel,
    resetTooltipLabel,
    extraSection,
    commandValue,
    onCommandValueChange,
    onCommandReset,
    modelsLoading,
    modelsError,
    favoriteModels,
    groupedModels,
    favoriteModelSet,
    onSelectModel,
    onToggleFavorite,
}: ModelSelectionDialogContentProps<TTarget>): JSX.Element => {
    const { className, ...restDialogContentProps } = dialogContentProps ?? {};
    const canDeletePreset = presetSelectValue !== defaultPresetValue;
    const selectedPresetLabel =
        presetSelectValue === defaultPresetValue ? "Custom" : presetSelectValue;
    const isTabValue = (value: string): value is TTarget =>
        tabs.some((tab) => tab.value === value);

    const renderResetButton = (): JSX.Element => {
        const button = (
            <Button
                aria-label={resetButtonAriaLabel}
                onClick={onResetCurrentTarget}
                size="icon-sm"
                type="button"
                variant="ghost"
            >
                <RotateCcw className="size-3" />
            </Button>
        );

        if (resetTooltipLabel === undefined) {
            return button;
        }

        return (
            <Tooltip>
                <TooltipTrigger render={button} />
                <TooltipContent side="top">{resetTooltipLabel}</TooltipContent>
            </Tooltip>
        );
    };

    const renderModelItem = (fullValue: string): JSX.Element => {
        const isFavorite = favoriteModelSet.has(fullValue);
        const isSelected = fullValue === currentTargetValue;
        return (
            <CommandItem
                className={
                    isSelected
                        ? "bg-accent/60 flex items-center gap-2"
                        : "flex items-center gap-2"
                }
                key={fullValue}
                onSelect={(selected) => {
                    if (typeof selected === "string") {
                        onSelectModel(selected);
                    }
                }}
                value={fullValue}
            >
                <span
                    aria-hidden="true"
                    className={
                        isSelected
                            ? "text-primary flex size-4 items-center"
                            : "text-muted-foreground flex size-4 items-center"
                    }
                >
                    {isSelected ? (
                        <Check className="size-4" />
                    ) : (
                        <span className="block size-2" />
                    )}
                </span>
                <span
                    className="break-all"
                    title={fullValue}
                >
                    {fullValue}
                </span>
                <button
                    aria-label={isFavorite ? "Remove favorite" : "Add favorite"}
                    aria-pressed={isFavorite}
                    className={
                        isFavorite
                            ? "text-primary ml-auto"
                            : "text-muted-foreground hover:text-foreground ml-auto"
                    }
                    onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        onToggleFavorite(fullValue);
                    }}
                    onPointerDown={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                    }}
                    type="button"
                >
                    <Star
                        className={
                            isFavorite
                                ? "text-primary size-4 fill-current"
                                : "size-4"
                        }
                    />
                </button>
            </CommandItem>
        );
    };

    return (
        <DialogContent
            className={cn("max-w-2xl", className)}
            {...restDialogContentProps}
        >
            <DialogHeader>
                <DialogTitle>{title}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <span className="text-muted-foreground text-xs">
                        Preset
                    </span>
                    <div className="flex items-center gap-2">
                        <div className="flex-1">
                            <Select
                                onValueChange={(value) => {
                                    if (value === null) {
                                        return;
                                    }

                                    onPresetSelect(value);
                                }}
                                value={presetSelectValue}
                            >
                                <SelectTrigger
                                    className="w-full"
                                    size="sm"
                                >
                                    <SelectValue placeholder="Custom">
                                        {selectedPresetLabel}
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value={defaultPresetValue}>
                                        Custom
                                    </SelectItem>
                                    {presets.map((preset) => (
                                        <SelectItem
                                            key={preset.name}
                                            value={preset.name}
                                        >
                                            {preset.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        aria-label="Delete preset"
                                        className="text-muted-foreground hover:text-foreground"
                                        disabled={!canDeletePreset}
                                        onClick={() => {
                                            if (canDeletePreset) {
                                                onRequestDeletePreset(
                                                    presetSelectValue,
                                                );
                                            }
                                        }}
                                        size="icon-sm"
                                        type="button"
                                        variant="ghost"
                                    >
                                        <Trash2 className="size-3" />
                                    </Button>
                                }
                            />
                            <TooltipContent side="top">
                                Delete preset
                            </TooltipContent>
                        </Tooltip>
                    </div>
                    <Dialog
                        onOpenChange={onDeletePresetOpenChange}
                        open={deletePresetOpen}
                    >
                        <DialogContent className="max-w-sm">
                            <DialogHeader>
                                <DialogTitle>Delete preset</DialogTitle>
                            </DialogHeader>
                            <p className="text-muted-foreground text-sm">
                                Delete preset
                                {deletePresetName === undefined
                                    ? ""
                                    : ` "${deletePresetName}"`}
                                ?
                            </p>
                            <DialogFooter>
                                <Button
                                    onClick={onDeletePresetCancel}
                                    type="button"
                                    variant="ghost"
                                >
                                    Cancel
                                </Button>
                                <Button
                                    onClick={onDeletePresetConfirm}
                                    type="button"
                                    variant="destructive"
                                >
                                    Delete
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                </div>
                <div className="flex flex-col gap-1">
                    <span className="text-muted-foreground text-xs">
                        Save current selection
                    </span>
                    <div className="flex items-center gap-2">
                        <Input
                            onChange={(event) => {
                                onPresetNameChange(event.target.value);
                            }}
                            placeholder="Preset name"
                            value={presetName}
                        />
                        <Button
                            disabled={isSaveDisabled}
                            onClick={onSavePreset}
                            size="sm"
                            type="button"
                            variant="secondary"
                        >
                            Save
                        </Button>
                    </div>
                </div>
            </div>
            <Tabs
                onValueChange={(value) => {
                    if (typeof value === "string" && isTabValue(value)) {
                        onModelTargetChange(value);
                    }
                }}
                value={modelTarget}
            >
                <TabsList>
                    {tabs.map((tab) => (
                        <TabsTrigger
                            key={tab.value}
                            value={tab.value}
                        >
                            {tab.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>
            <div className="text-muted-foreground flex items-center gap-2 text-xs">
                <span>Current: {currentTargetValue || "Default"}</span>
                {renderResetButton()}
            </div>
            {extraSection}
            <Command
                className="rounded-lg border"
                onValueChange={onCommandValueChange}
                value={commandValue}
            >
                <CommandInput placeholder="Search models..." />
                <CommandList
                    onMouseLeave={() => {
                        onCommandReset();
                    }}
                >
                    <CommandEmpty>
                        {modelsLoading
                            ? "Loading models..."
                            : modelsError === undefined
                              ? "No models found."
                              : "Models unavailable"}
                    </CommandEmpty>
                    {modelsError !== undefined && (
                        <div className="text-destructive px-3 py-2 text-xs">
                            {modelsError}
                        </div>
                    )}
                    {!modelsLoading && modelsError === undefined && (
                        <>
                            {favoriteModels.length > 0 && (
                                <>
                                    <CommandGroup heading="Favorites">
                                        {favoriteModels.map((model) =>
                                            renderModelItem(model),
                                        )}
                                    </CommandGroup>
                                    <CommandSeparator />
                                </>
                            )}
                            {groupedModels.map((group) => (
                                <CommandGroup
                                    heading={group.provider}
                                    key={group.provider}
                                >
                                    {group.models.map((model) => {
                                        const fullValue =
                                            group.provider === "default"
                                                ? model
                                                : `${group.provider}:${model}`;
                                        return renderModelItem(fullValue);
                                    })}
                                </CommandGroup>
                            ))}
                        </>
                    )}
                </CommandList>
            </Command>
        </DialogContent>
    );
};
