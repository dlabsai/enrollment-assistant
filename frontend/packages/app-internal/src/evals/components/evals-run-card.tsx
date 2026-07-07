import { Button } from "@va/shared/components/ui/button";
import { Dialog, DialogTrigger } from "@va/shared/components/ui/dialog";
import { Input } from "@va/shared/components/ui/input";
import { Label } from "@va/shared/components/ui/label";
import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import { SlidersHorizontal } from "lucide-react";
import {
    Fragment,
    type JSX,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { ModelSelectionDialogContent } from "../../components/model-selection-dialog-content";
import { InlineError } from "../../components/page-state";
import {
    cancelEvalRun,
    fetchCurrentEvalRun,
    fetchEvalTestCases,
    fetchInternalModels,
    runEvalStream,
    streamExistingEvalRun,
} from "../lib/api";
import {
    type EvalModelPreset,
    readStoredModelConfig,
    readStoredModelFavorites,
    readStoredModelPresets,
    writeStoredModelConfig,
    writeStoredModelFavorites,
    writeStoredModelPresets,
} from "../lib/model-storage";
import { parsePassThreshold, parsePositiveInt } from "../lib/run-utils";
import type {
    EvalRunLogEntry,
    EvalRunReportEvent,
    EvalRunRequest,
    EvalRunStatusEvent,
    EvalSuite,
} from "../types";
import { TestCaseSelector } from "./test-case-selector";

const evalSuiteOptions: { label: string; value: EvalSuite }[] = [
    { label: "Chatbot", value: "chatbot" },
    { label: "Guardrails", value: "guardrails" },
];

const DEFAULT_PRESET_VALUE = "__default_preset__";
const COMMAND_UNSELECTED_VALUE = "__va_model_unselected__";
type EvalModelTarget = "chatbot" | "guardrails" | "judge";

const EVAL_MODEL_TARGET_TABS: { value: EvalModelTarget; label: string }[] = [
    { value: "chatbot", label: "Chatbot" },
    { value: "guardrails", label: "Guardrails" },
    { value: "judge", label: "Judge" },
];

interface EvalRunLogItem extends EvalRunLogEntry {
    id: string;
}

interface EvalsRunCardProps {
    onOpenReport: (reportId: string) => void;
}

export const EvalsRunCard = ({
    onOpenReport,
}: EvalsRunCardProps): JSX.Element => {
    const api = useAuthenticatedApi();
    const [runSuite, setRunSuite] = useState<EvalSuite>("chatbot");
    const [runRepeat, setRunRepeat] = useState("1");
    const [runConcurrency, setRunConcurrency] = useState("5");
    const [runPassThreshold, setRunPassThreshold] = useState("0.9");
    const [selectedTestCases, setSelectedTestCases] = useState<string[]>([]);
    const [testCasesLoading, setTestCasesLoading] = useState(false);
    const [testCasesError, setTestCasesError] = useState<string | undefined>();
    const [availableTestCases, setAvailableTestCases] = useState<string[]>([]);
    const [availableModels, setAvailableModels] = useState<string[]>([]);
    const [modelsLoading, setModelsLoading] = useState(true);
    const [modelsError, setModelsError] = useState<string | undefined>();
    const [commandValue, setCommandValue] = useState(COMMAND_UNSELECTED_VALUE);
    const [runChatbotModel, setRunChatbotModel] = useState(() => {
        const stored = readStoredModelConfig();
        return typeof stored?.chatbotModel === "string"
            ? stored.chatbotModel
            : "";
    });
    const [runGuardrailModel, setRunGuardrailModel] = useState(() => {
        const stored = readStoredModelConfig();
        return typeof stored?.guardrailModel === "string"
            ? stored.guardrailModel
            : "";
    });
    const [runEvaluationModel, setRunEvaluationModel] = useState(() => {
        const stored = readStoredModelConfig();
        return typeof stored?.evaluationModel === "string"
            ? stored.evaluationModel
            : "";
    });
    const [favoriteModels, setFavoriteModels] = useState(() =>
        readStoredModelFavorites(),
    );
    const [modelPresets, setModelPresets] = useState(() =>
        readStoredModelPresets(),
    );
    const [presetName, setPresetName] = useState("");
    const [deletePresetOpen, setDeletePresetOpen] = useState(false);
    const [deletePresetName, setDeletePresetName] = useState<
        string | undefined
    >();
    const [modelTarget, setModelTarget] = useState<EvalModelTarget>("chatbot");
    const [isModelDialogOpen, setIsModelDialogOpen] = useState(false);
    const [runStatus, setRunStatus] = useState<
        EvalRunStatusEvent["status"] | "idle"
    >("idle");
    const [currentRunId, setCurrentRunId] = useState<string | undefined>();
    const [latestReportId, setLatestReportId] = useState<string | undefined>();
    const [runLogs, setRunLogs] = useState<EvalRunLogItem[]>([]);
    const [runError, setRunError] = useState<string | undefined>();
    const runAbortControllerRef = useRef<AbortController | undefined>(
        undefined,
    );
    const runOutputContainerRef = useRef<HTMLDivElement | null>(null);
    const runLogCounterRef = useRef(0);

    const testCasesEmptyLabel = testCasesLoading
        ? "Loading test cases..."
        : (testCasesError ?? "No test cases found");

    const appendRunLog = useCallback((entry: EvalRunLogEntry) => {
        setRunLogs((prev) => {
            const next = [
                ...prev,
                {
                    ...entry,
                    id: `log-${runLogCounterRef.current}`,
                },
            ];
            runLogCounterRef.current += 1;
            return next;
        });
    }, []);

    const handleRunStatus = useCallback((status: EvalRunStatusEvent): void => {
        setRunStatus(status.status);
        if (status.runId !== undefined) {
            setCurrentRunId(status.runId);
        }
    }, []);

    const handleRunReport = useCallback((report: EvalRunReportEvent): void => {
        if (report.runId !== undefined) {
            setCurrentRunId(report.runId);
        }
        setLatestReportId(report.reportId);
    }, []);

    const handleRunError = useCallback((message: string): void => {
        setRunError(message);
    }, []);

    useEffect((): (() => void) => {
        let mounted = true;

        const streamCurrentRun = async (runId: string): Promise<void> => {
            if (runAbortControllerRef.current !== undefined) {
                runAbortControllerRef.current.abort();
            }
            const controller = new AbortController();
            runAbortControllerRef.current = controller;
            runLogCounterRef.current = 0;
            setRunLogs([]);
            setRunError(undefined);
            try {
                await streamExistingEvalRun(
                    api,
                    runId,
                    {
                        onLog: appendRunLog,
                        onStatus: handleRunStatus,
                        onReport: handleRunReport,
                        onError: handleRunError,
                    },
                    controller.signal,
                );
            } catch (error_) {
                if (
                    error_ instanceof DOMException &&
                    error_.name === "AbortError"
                ) {
                    return;
                }
                setRunError(
                    error_ instanceof Error
                        ? error_.message
                        : "Failed to stream eval run",
                );
                setRunStatus("error");
            } finally {
                if (runAbortControllerRef.current === controller) {
                    runAbortControllerRef.current = undefined;
                }
            }
        };

        void fetchCurrentEvalRun(api)
            .then((run) => {
                if (!mounted || run === null) {
                    return;
                }
                setCurrentRunId(run.runId);
                setRunStatus(run.status);
                if (run.errorMessage !== null) {
                    setRunError(run.errorMessage);
                }
                if (run.reportId !== null) {
                    setLatestReportId(run.reportId);
                }
                void streamCurrentRun(run.runId);
            })
            .catch((error: unknown) => {
                if (!mounted) {
                    return;
                }
                setRunError(
                    error instanceof Error
                        ? error.message
                        : "Failed to load current eval run",
                );
            });

        return () => {
            mounted = false;
            if (runAbortControllerRef.current !== undefined) {
                runAbortControllerRef.current.abort();
                runAbortControllerRef.current = undefined;
            }
        };
    }, [api, appendRunLog, handleRunError, handleRunReport, handleRunStatus]);

    useEffect(() => {
        writeStoredModelConfig({
            chatbotModel: runChatbotModel,
            guardrailModel: runGuardrailModel,
            evaluationModel: runEvaluationModel,
        });
    }, [
        runChatbotModel,
        runEvaluationModel,
        runGuardrailModel,
    ]);

    useEffect(() => {
        writeStoredModelFavorites(favoriteModels);
    }, [favoriteModels]);

    useEffect(() => {
        writeStoredModelPresets(modelPresets);
    }, [modelPresets]);

    useEffect(() => {
        if (runOutputContainerRef.current !== null) {
            runOutputContainerRef.current.scrollTop =
                runOutputContainerRef.current.scrollHeight;
        }
    }, [runLogs]);

    useEffect((): (() => void) | undefined => {
        let mounted = true;
        void fetchInternalModels(api)
            .then((models) => {
                if (!mounted) {
                    return;
                }
                const uniqueModels = [
                    ...new Set(
                        models
                            .map((model) => model.trim())
                            .filter((model) => model !== ""),
                    ),
                ];
                setAvailableModels(uniqueModels);
            })
            .catch((error: unknown) => {
                if (!mounted) {
                    return;
                }
                setModelsError(
                    error instanceof Error
                        ? error.message
                        : "Failed to load models",
                );
            })
            .finally(() => {
                if (!mounted) {
                    return;
                }
                setModelsLoading(false);
            });

        return () => {
            mounted = false;
        };
    }, [api]);

    useEffect((): (() => void) | undefined => {
        let mounted = true;

        const timeout = setTimeout(() => {
            if (!mounted) {
                return;
            }
            setTestCasesLoading(true);
            setTestCasesError(undefined);
            setAvailableTestCases([]);
            setSelectedTestCases([]);
        }, 0);

        void fetchEvalTestCases(api, runSuite)
            .then((cases) => {
                if (!mounted) {
                    return;
                }
                const uniqueCases = [
                    ...new Set(
                        cases
                            .map((value) => value.trim())
                            .filter((value) => value !== ""),
                    ),
                ];
                setAvailableTestCases(uniqueCases);
            })
            .catch((error: unknown) => {
                if (!mounted) {
                    return;
                }
                setTestCasesError(
                    error instanceof Error
                        ? error.message
                        : "Failed to load test cases",
                );
            })
            .finally(() => {
                if (!mounted) {
                    return;
                }
                setTestCasesLoading(false);
            });

        return () => {
            mounted = false;
            clearTimeout(timeout);
        };
    }, [api, runSuite]);

    const handleRun = useCallback(async (): Promise<void> => {
        if (runAbortControllerRef.current !== undefined) {
            return;
        }
        const repeat = parsePositiveInt(runRepeat, 1);
        const maxConcurrency = parsePositiveInt(runConcurrency, 5);
        const passThreshold = parsePassThreshold(runPassThreshold, 0.9);
        const testCaseValues = selectedTestCases
            .map((value) => value.trim())
            .filter((value) => value !== "");
        const testCases = testCaseValues.join(",");
        const chatbotModel = runChatbotModel.trim();
        const guardrailModel = runGuardrailModel.trim();
        const evaluationModel = runEvaluationModel.trim();

        const payload: EvalRunRequest = {
            suite: runSuite,
            repeat,
            maxConcurrency,
            passThreshold,
            testCases: testCases === "" ? undefined : testCases,
            chatbotModel: chatbotModel === "" ? undefined : chatbotModel,
            guardrailModel: guardrailModel === "" ? undefined : guardrailModel,
            evaluationModel:
                evaluationModel === "" ? undefined : evaluationModel,
        };

        const controller = new AbortController();
        runAbortControllerRef.current = controller;
        runLogCounterRef.current = 0;
        setRunLogs([]);
        setRunError(undefined);
        setCurrentRunId(undefined);
        setLatestReportId(undefined);
        setRunStatus("start");

        try {
            await runEvalStream(
                api,
                payload,
                {
                    onLog: appendRunLog,
                    onStatus: handleRunStatus,
                    onReport: handleRunReport,
                    onError: handleRunError,
                },
                controller.signal,
            );
        } catch (error_) {
            if (
                error_ instanceof DOMException &&
                error_.name === "AbortError"
            ) {
                return;
            }
            setRunError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to run evals",
            );
            setRunStatus("error");
        } finally {
            if (runAbortControllerRef.current === controller) {
                runAbortControllerRef.current = undefined;
            }
        }
    }, [
        api,
        appendRunLog,
        handleRunError,
        handleRunReport,
        handleRunStatus,
        runChatbotModel,
        runConcurrency,
        runEvaluationModel,
        runGuardrailModel,
        runPassThreshold,
        runRepeat,
        runSuite,
        selectedTestCases,
    ]);

    const handleStop = useCallback((): void => {
        if (currentRunId === undefined) {
            if (runAbortControllerRef.current !== undefined) {
                runAbortControllerRef.current.abort();
            }
            return;
        }
        void cancelEvalRun(api, currentRunId)
            .then((run) => {
                setRunStatus(run.status);
                if (run.errorMessage !== null) {
                    setRunError(run.errorMessage);
                }
            })
            .catch((error: unknown) => {
                setRunError(
                    error instanceof Error
                        ? error.message
                        : "Failed to cancel eval run",
                );
            })
            .finally(() => {
                if (runAbortControllerRef.current !== undefined) {
                    runAbortControllerRef.current.abort();
                }
            });
    }, [api, currentRunId]);

    const favoriteModelsAvailable = useMemo(
        () => favoriteModels.filter((model) => availableModels.includes(model)),
        [favoriteModels, availableModels],
    );

    const favoriteModelSet = useMemo(
        () => new Set(favoriteModelsAvailable),
        [favoriteModelsAvailable],
    );

    const sortedFavoriteModels = useMemo(
        () =>
            favoriteModelsAvailable.toSorted((left, right) =>
                left.localeCompare(right),
            ),
        [favoriteModelsAvailable],
    );

    const groupedModels = useMemo(() => {
        const groups = new Map<string, string[]>();
        for (const model of availableModels) {
            if (!favoriteModelSet.has(model)) {
                const separatorIndex = model.indexOf(":");
                const provider =
                    separatorIndex > 0
                        ? model.slice(0, separatorIndex)
                        : "default";
                const name =
                    separatorIndex > 0
                        ? model.slice(separatorIndex + 1)
                        : model;
                const entries = groups.get(provider) ?? [];
                entries.push(name);
                groups.set(provider, entries);
            }
        }
        return [...groups.entries()].map(([provider, models]) => ({
            provider,
            models: models.toSorted((left, right) => left.localeCompare(right)),
        }));
    }, [availableModels, favoriteModelSet]);

    const currentTargetValue =
        modelTarget === "guardrails"
            ? runGuardrailModel
            : modelTarget === "judge"
                ? runEvaluationModel
                : runChatbotModel;

    const setModelForTarget = (value: string): void => {
        const normalizedValue = value === "" ? "" : value;
        if (modelTarget === "guardrails") {
            setRunGuardrailModel(normalizedValue);
            return;
        }
        if (modelTarget === "judge") {
            setRunEvaluationModel(normalizedValue);
            return;
        }
        setRunChatbotModel(normalizedValue);
    };

    const resetCurrentTarget = (): void => {
        setModelForTarget("");
    };

    const toggleFavoriteModel = (model: string): void => {
        setFavoriteModels((current) => {
            if (current.includes(model)) {
                return current.filter((entry) => entry !== model);
            }
            return [...current, model];
        });
    };

    const modelOverrideSummary = useMemo((): string[] => {
        const summary: string[] = [];
        if (runChatbotModel !== "") {
            summary.push(`Chatbot: ${runChatbotModel}`);
        }
        if (runGuardrailModel !== "") {
            summary.push(`Guardrails: ${runGuardrailModel}`);
        }
        if (runEvaluationModel !== "") {
            summary.push(`Judge: ${runEvaluationModel}`);
        }
        return summary;
    }, [
        runChatbotModel,
        runEvaluationModel,
        runGuardrailModel,
    ]);

    const hasModelOverrides = modelOverrideSummary.length > 0;

    const activePresetName = useMemo(() => {
        for (const preset of modelPresets) {
            if (
                (preset.chatbotModel ?? "") === runChatbotModel &&
                (preset.guardrailModel ?? "") === runGuardrailModel &&
                (preset.evaluationModel ?? "") === runEvaluationModel
            ) {
                return preset.name;
            }
        }
        return "";
    }, [
        modelPresets,
        runChatbotModel,
        runEvaluationModel,
        runGuardrailModel,
    ]);

    const sortedPresets = useMemo(
        () =>
            [...modelPresets].toSorted((left, right) =>
                left.name.localeCompare(right.name),
            ),
        [modelPresets],
    );

    const presetSelectValue =
        activePresetName === "" ? DEFAULT_PRESET_VALUE : activePresetName;

    const buildPresetFromCurrent = (name: string): EvalModelPreset => {
        const preset: EvalModelPreset = { name };
        if (runChatbotModel !== "") {
            preset.chatbotModel = runChatbotModel;
        }
        if (runGuardrailModel !== "") {
            preset.guardrailModel = runGuardrailModel;
        }
        if (runEvaluationModel !== "") {
            preset.evaluationModel = runEvaluationModel;
        }
        return preset;
    };

    const applyPreset = (preset: EvalModelPreset): void => {
        setRunChatbotModel(preset.chatbotModel ?? "");
        setRunGuardrailModel(preset.guardrailModel ?? "");
        setRunEvaluationModel(preset.evaluationModel ?? "");
    };

    const handlePresetSelect = (value: string): void => {
        if (value === DEFAULT_PRESET_VALUE) {
            return;
        }
        const preset = modelPresets.find((entry) => entry.name === value);
        if (!preset) {
            return;
        }
        applyPreset(preset);
    };

    const handleSavePreset = (): void => {
        const trimmed = presetName.trim();
        if (trimmed === "") {
            toast.error("Preset name is required");
            return;
        }
        const nextPreset = buildPresetFromCurrent(trimmed);
        setModelPresets((current) => {
            const withoutExisting = current.filter(
                (preset) => preset.name !== trimmed,
            );
            return [...withoutExisting, nextPreset];
        });
        setPresetName("");
        toast.success(`Saved preset "${trimmed}"`);
    };

    const openDeletePresetDialog = (name: string): void => {
        const existing = modelPresets.find((preset) => preset.name === name);
        if (!existing) {
            return;
        }
        setDeletePresetName(name);
        setDeletePresetOpen(true);
    };

    const handleDeletePreset = (): void => {
        const name = deletePresetName;
        if (name === undefined || name === "") {
            return;
        }
        setModelPresets((current) =>
            current.filter((preset) => preset.name !== name),
        );
        setDeletePresetOpen(false);
        setDeletePresetName(undefined);
        toast.success(`Deleted preset "${name}"`);
    };

    const selectedSuiteLabel =
        evalSuiteOptions.find((option) => option.value === runSuite)?.label ??
        "Select suite";
    const runIsRunning = runStatus === "start";

    return (
        <ResizablePanelGroup
            className="h-full min-h-0 min-w-0"
            id="eval-runner-layout"
            orientation="horizontal"
            style={{ overflow: "visible" }}
        >
            <ResizablePanel
                className="min-h-0 min-w-0"
                defaultSize="50%"
                id="eval-runner-controls-panel"
                minSize="22%"
                style={{ overflow: "visible" }}
            >
                <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto rounded-md border p-4">
                    <div className="grid gap-3 @lg/main:grid-cols-4 @2xl/main:grid-cols-2">
                        <div className="flex flex-col gap-1">
                            <Label className="text-muted-foreground text-xs">
                                Suite
                            </Label>
                            <Select
                                onValueChange={(value) => {
                                    if (
                                        value === "chatbot" ||
                                        value === "guardrails"
                                    ) {
                                        setRunSuite(value);
                                    }
                                }}
                                value={runSuite}
                            >
                                <SelectTrigger className="w-full">
                                    <SelectValue placeholder="Select suite">
                                        {selectedSuiteLabel}
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        {evalSuiteOptions.map((suite) => (
                                            <SelectItem
                                                key={suite.value}
                                                value={suite.value}
                                            >
                                                {suite.label}
                                            </SelectItem>
                                        ))}
                                    </SelectGroup>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="flex flex-col gap-1">
                            <Label className="text-muted-foreground text-xs">
                                Repeats
                            </Label>
                            <Input
                                min={1}
                                onChange={(event) => {
                                    setRunRepeat(event.target.value);
                                }}
                                type="number"
                                value={runRepeat}
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <Label className="text-muted-foreground text-xs">
                                Concurrency
                            </Label>
                            <Input
                                min={1}
                                onChange={(event) => {
                                    setRunConcurrency(event.target.value);
                                }}
                                type="number"
                                value={runConcurrency}
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <Label className="text-muted-foreground text-xs">
                                Pass threshold
                            </Label>
                            <Input
                                max={1}
                                min={0.1}
                                onChange={(event) => {
                                    setRunPassThreshold(event.target.value);
                                }}
                                step={0.01}
                                type="number"
                                value={runPassThreshold}
                            />
                        </div>
                        <div className="flex flex-col gap-1 @lg/main:col-span-4 @2xl/main:col-span-2">
                            <Label className="text-muted-foreground text-xs">
                                Test case IDs
                            </Label>
                            <TestCaseSelector
                                allowCustomValues
                                emptyLabel={testCasesEmptyLabel}
                                onSelectedValuesChange={setSelectedTestCases}
                                options={availableTestCases}
                                placeholder="Search or add test cases..."
                                selectedValues={selectedTestCases}
                            />
                        </div>
                        <div className="flex flex-col gap-2 @lg/main:col-span-4 @2xl/main:col-span-2">
                            <Label className="text-muted-foreground text-xs">
                                Models (optional)
                            </Label>
                            <div className="flex flex-wrap items-center gap-2">
                                <Dialog
                                    onOpenChange={(nextOpen) => {
                                        setIsModelDialogOpen(nextOpen);
                                        if (nextOpen) {
                                            setCommandValue(
                                                COMMAND_UNSELECTED_VALUE,
                                            );
                                        }
                                    }}
                                    open={isModelDialogOpen}
                                >
                                    <DialogTrigger
                                        render={
                                            <Button
                                                size="sm"
                                                type="button"
                                                variant="outline"
                                            >
                                                <SlidersHorizontal data-icon="inline-start" />
                                                Model selection
                                            </Button>
                                        }
                                    />
                                    <ModelSelectionDialogContent
                                        commandValue={commandValue}
                                        currentTargetValue={currentTargetValue}
                                        defaultPresetValue={
                                            DEFAULT_PRESET_VALUE
                                        }
                                        deletePresetName={deletePresetName}
                                        deletePresetOpen={deletePresetOpen}
                                        favoriteModelSet={favoriteModelSet}
                                        favoriteModels={sortedFavoriteModels}
                                        groupedModels={groupedModels}
                                        isSaveDisabled={
                                            presetName.trim() === ""
                                        }
                                        modelTarget={modelTarget}
                                        modelsError={modelsError}
                                        modelsLoading={modelsLoading}
                                        onCommandReset={() => {
                                            setCommandValue(
                                                COMMAND_UNSELECTED_VALUE,
                                            );
                                        }}
                                        onCommandValueChange={setCommandValue}
                                        onDeletePresetCancel={() => {
                                            setDeletePresetOpen(false);
                                            setDeletePresetName(undefined);
                                        }}
                                        onDeletePresetConfirm={
                                            handleDeletePreset
                                        }
                                        onDeletePresetOpenChange={(
                                            nextOpen,
                                        ) => {
                                            setDeletePresetOpen(nextOpen);
                                            if (!nextOpen) {
                                                setDeletePresetName(undefined);
                                            }
                                        }}
                                        onModelTargetChange={setModelTarget}
                                        onPresetNameChange={setPresetName}
                                        onPresetSelect={handlePresetSelect}
                                        onRequestDeletePreset={
                                            openDeletePresetDialog
                                        }
                                        onResetCurrentTarget={
                                            resetCurrentTarget
                                        }
                                        onSavePreset={handleSavePreset}
                                        onSelectModel={setModelForTarget}
                                        onToggleFavorite={toggleFavoriteModel}
                                        presetName={presetName}
                                        presetSelectValue={presetSelectValue}
                                        presets={sortedPresets}
                                        resetButtonAriaLabel="Reset model to default"
                                        tabs={EVAL_MODEL_TARGET_TABS}
                                    />
                                </Dialog>
                                {hasModelOverrides && (
                                    <Button
                                        onClick={() => {
                                            setRunChatbotModel("");
                                            setRunGuardrailModel("");
                                            setRunEvaluationModel("");
                                        }}
                                        size="sm"
                                        type="button"
                                        variant="ghost"
                                    >
                                        Reset models
                                    </Button>
                                )}
                            </div>
                            {hasModelOverrides ? (
                                <div className="text-muted-foreground text-xs">
                                    {modelOverrideSummary.join(" · ")}
                                </div>
                            ) : (
                                <div className="text-muted-foreground text-xs">
                                    Using default models.
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button
                            disabled={runIsRunning}
                            onClick={() => void handleRun()}
                            size="sm"
                        >
                            Run evals
                        </Button>
                        <Button
                            disabled={!runIsRunning}
                            onClick={handleStop}
                            size="sm"
                            variant="outline"
                        >
                            Stop
                        </Button>
                        <Button
                            onClick={() => {
                                runLogCounterRef.current = 0;
                                setRunLogs([]);
                                setRunError(undefined);
                                setRunStatus("idle");
                            }}
                            size="sm"
                            variant="outline"
                        >
                            Clear logs
                        </Button>
                        <Button
                            disabled={latestReportId === undefined}
                            onClick={() => {
                                if (latestReportId !== undefined) {
                                    onOpenReport(latestReportId);
                                }
                            }}
                            size="sm"
                            variant="outline"
                        >
                            View report
                        </Button>
                    </div>
                </div>
            </ResizablePanel>
            <ResizableHandle
                className="mx-2 aria-[orientation=horizontal]:mx-0 aria-[orientation=horizontal]:my-2"
                withHandle
            />
            <ResizablePanel
                className="min-h-0 min-w-0"
                defaultSize="50%"
                id="eval-runner-output-panel"
                minSize="22%"
                style={{ overflow: "visible" }}
            >
                <div className="flex h-full min-h-0 flex-col gap-3">
                    {runError !== undefined && (
                        <InlineError message={runError} />
                    )}
                    <div
                        className="bg-muted/20 min-h-0 flex-1 overflow-auto rounded-md border p-4"
                        ref={runOutputContainerRef}
                    >
                        <pre className="font-mono text-sm leading-relaxed break-words whitespace-pre-wrap">
                            {runLogs.map((entry) => (
                                <Fragment key={entry.id}>
                                    {entry.message}
                                    {"\n"}
                                </Fragment>
                            ))}
                            {runIsRunning && (
                                <span className="bg-foreground ml-0.5 inline-block h-4 w-2 animate-pulse align-middle" />
                            )}
                        </pre>
                    </div>
                </div>
            </ResizablePanel>
        </ResizablePanelGroup>
    );
};
