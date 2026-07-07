import { useNavigate, useSearch } from "@tanstack/react-router";
import type {
    ColumnDef,
    OnChangeFn,
    PaginationState,
    SortingState,
} from "@tanstack/react-table";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@va/shared/components/ui/alert-dialog";
import { Button } from "@va/shared/components/ui/button";
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
import { Switch } from "@va/shared/components/ui/switch";
import { Textarea } from "@va/shared/components/ui/textarea";
import { cn } from "@va/shared/lib/utils";
import { Plus, RefreshCw, Save, Trash2, X } from "lucide-react";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { DataTable } from "../../components/data-table";
import { isDataTablePageSize } from "../../components/data-table-constants";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError, PageError } from "../../components/page-state";
import {
    createEvalCaseDefinition,
    deleteEvalCaseDefinition,
    fetchEvalCaseDefinitions,
    updateEvalCaseDefinition,
} from "../lib/api";
import {
    type EvalCasesSearch,
    isEvalCasesSortBy,
} from "../lib/case-search-state";
import type { EvalCaseDefinition, EvalSuite } from "../types";

const evalSuiteOptions: { label: string; value: EvalSuite }[] = [
    { label: "Chatbot", value: "chatbot" },
    { label: "Guardrails", value: "guardrails" },
];

interface EvalCaseDraft {
    testCaseId: string;
    userInput: string;
    criteria: string;
    chatbotResponse: string;
    expectedValid: boolean;
    isInternal: boolean;
}

const emptyDraft = (): EvalCaseDraft => ({
    testCaseId: "",
    userInput: "",
    criteria: "",
    chatbotResponse: "",
    expectedValid: true,
    isInternal: true,
});

const stringValue = (
    payload: Record<string, unknown> | null | undefined,
    key: string,
): string => {
    const value = payload?.[key];
    return typeof value === "string" ? value : "";
};

const booleanValue = (
    payload: Record<string, unknown> | null | undefined,
    key: string,
    fallback: boolean,
): boolean => {
    const value = payload?.[key];
    return typeof value === "boolean" ? value : fallback;
};

const draftFromPayload = (
    suite: EvalSuite,
    payload: Record<string, unknown> | null | undefined,
): EvalCaseDraft => ({
    testCaseId: stringValue(payload, "test_case_id"),
    userInput: suite === "chatbot" ? stringValue(payload, "user_input") : "",
    criteria: stringValue(payload, "criteria"),
    chatbotResponse:
        suite === "guardrails" ? stringValue(payload, "chatbot_response") : "",
    expectedValid:
        suite === "guardrails"
            ? booleanValue(payload, "expected_valid", true)
            : true,
    isInternal:
        suite === "chatbot" ? booleanValue(payload, "is_internal", true) : true,
});

const payloadFromDraft = (
    suite: EvalSuite,
    draft: EvalCaseDraft,
): Record<string, unknown> => {
    const common = {
        test_case_id: draft.testCaseId.trim(),
        criteria: draft.criteria.trim(),
    };
    if (suite === "chatbot") {
        return {
            ...common,
            user_input: draft.userInput.trim(),
            is_internal: draft.isInternal,
        };
    }
    return {
        ...common,
        chatbot_response: draft.chatbotResponse.trim(),
        expected_valid: draft.expectedValid,
    };
};

const selectedSuiteLabel = (suite: EvalSuite): string =>
    evalSuiteOptions.find((option) => option.value === suite)?.label ?? suite;

const caseListMessage = (
    suite: EvalSuite,
    payload: Record<string, unknown>,
): string =>
    suite === "chatbot"
        ? stringValue(payload, "user_input")
        : stringValue(payload, "chatbot_response");

const caseListCriteria = (payload: Record<string, unknown>): string =>
    stringValue(payload, "criteria");

const caseListExpected = (payload: Record<string, unknown>): string =>
    booleanValue(payload, "expected_valid", true) ? "Valid" : "Invalid";

const draftsEqual = (left: EvalCaseDraft, right: EvalCaseDraft): boolean =>
    left.testCaseId === right.testCaseId &&
    left.userInput === right.userInput &&
    left.criteria === right.criteria &&
    left.chatbotResponse === right.chatbotResponse &&
    left.expectedValid === right.expectedValid &&
    left.isInternal === right.isInternal;

const buildCaseColumns = (
    suite: EvalSuite,
): ColumnDef<EvalCaseDefinition>[] => {
    const columns: ColumnDef<EvalCaseDefinition>[] = [
        {
            id: "case_id",
            accessorFn: (caseDefinition) => caseDefinition.caseId,
            header: "ID",
            enableSorting: true,
            cell: ({ row }) => (
                <span className="block truncate font-medium">
                    {row.original.caseId}
                </span>
            ),
        },
        {
            id: "message",
            accessorFn: (caseDefinition) =>
                caseListMessage(suite, caseDefinition.payload),
            header: suite === "chatbot" ? "User message" : "Response",
            enableSorting: true,
            cell: ({ row }) => (
                <span className="block truncate">
                    {caseListMessage(suite, row.original.payload) || "—"}
                </span>
            ),
        },
    ];

    if (suite === "guardrails") {
        columns.push({
            id: "expected",
            accessorFn: (caseDefinition) =>
                caseListExpected(caseDefinition.payload),
            header: "Expected",
            enableSorting: true,
            cell: ({ row }) => caseListExpected(row.original.payload),
        });
    }

    columns.push({
        id: "criteria",
        accessorFn: (caseDefinition) =>
            caseListCriteria(caseDefinition.payload),
        header: "Criteria",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground block truncate">
                {caseListCriteria(row.original.payload) || "—"}
            </span>
        ),
    });

    return columns;
};

interface CaseReadOnlyFieldProps {
    label: string;
    value: string;
    className?: string;
}

const CaseReadOnlyField = ({
    label,
    value,
    className,
}: CaseReadOnlyFieldProps): JSX.Element => (
    <div className="flex flex-col gap-1.5">
        <Label>{label}</Label>
        <div
            className={cn(
                "border-input dark:bg-input/30 w-full rounded-lg border bg-transparent px-2.5 py-2 text-base whitespace-pre-wrap md:text-sm",
                className,
            )}
        >
            {value === "" ? "—" : value}
        </div>
    </div>
);

interface CaseFormProps {
    draft: EvalCaseDraft;
    editing: boolean;
    existingCase: boolean;
    saving: boolean;
    suite: EvalSuite;
    onDraftChange: (draft: EvalCaseDraft) => void;
}

const CaseForm = ({
    draft,
    editing,
    existingCase,
    saving,
    suite,
    onDraftChange,
}: CaseFormProps): JSX.Element => {
    if (!editing) {
        return (
            <div className="flex flex-col gap-4">
                {suite === "chatbot" ? (
                    <>
                        <CaseReadOnlyField
                            label="Audience"
                            value={draft.isInternal ? "Internal" : "Public"}
                        />
                        <CaseReadOnlyField
                            className="min-h-40"
                            label="User message"
                            value={draft.userInput}
                        />
                    </>
                ) : (
                    <>
                        <CaseReadOnlyField
                            className="min-h-36"
                            label="Chatbot response to validate"
                            value={draft.chatbotResponse}
                        />
                        <CaseReadOnlyField
                            label="Expected valid"
                            value={draft.expectedValid ? "Yes" : "No"}
                        />
                    </>
                )}
                <CaseReadOnlyField
                    className="min-h-40"
                    label="Evaluation criteria"
                    value={draft.criteria}
                />
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-4">
            {!existingCase && (
                <div className="flex flex-col gap-1.5">
                    <Label htmlFor="eval-case-id">Eval case ID</Label>
                    <Input
                        disabled={saving}
                        id="eval-case-id"
                        onChange={(event) => {
                            onDraftChange({
                                ...draft,
                                testCaseId: event.target.value,
                            });
                        }}
                        placeholder="internal_example_case"
                        value={draft.testCaseId}
                    />
                    <p className="text-muted-foreground text-xs">
                        IDs must be stable and cannot be changed after creation.
                    </p>
                </div>
            )}

            {suite === "chatbot" ? (
                <>
                    <div className="flex items-center gap-3 rounded-md border px-3 py-2">
                        <Switch
                            checked={draft.isInternal}
                            disabled={saving}
                            onCheckedChange={(checked) => {
                                onDraftChange({
                                    ...draft,
                                    isInternal: checked,
                                });
                            }}
                        />
                        <div className="flex flex-col gap-0.5">
                            <span className="text-sm font-medium">
                                Internal case
                            </span>
                            <span className="text-muted-foreground text-xs">
                                Internal cases can use staff-only sources; public
                                cases cannot.
                            </span>
                        </div>
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="eval-case-user-input">
                            User message
                        </Label>
                        <Textarea
                            className="min-h-40"
                            disabled={saving}
                            id="eval-case-user-input"
                            onChange={(event) => {
                                onDraftChange({
                                    ...draft,
                                    userInput: event.target.value,
                                });
                            }}
                            value={draft.userInput}
                        />
                    </div>
                </>
            ) : (
                <>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="eval-case-chatbot-response">
                            Chatbot response to validate
                        </Label>
                        <Textarea
                            className="min-h-36"
                            disabled={saving}
                            id="eval-case-chatbot-response"
                            onChange={(event) => {
                                onDraftChange({
                                    ...draft,
                                    chatbotResponse: event.target.value,
                                });
                            }}
                            value={draft.chatbotResponse}
                        />
                    </div>
                    <div className="flex items-center gap-3 rounded-md border px-3 py-2">
                        <Switch
                            checked={draft.expectedValid}
                            disabled={saving}
                            onCheckedChange={(checked) => {
                                onDraftChange({
                                    ...draft,
                                    expectedValid: checked,
                                });
                            }}
                        />
                        <div className="flex flex-col gap-0.5">
                            <span className="text-sm font-medium">
                                Expected valid
                            </span>
                            <span className="text-muted-foreground text-xs">
                                Whether guardrails should accept this response.
                            </span>
                        </div>
                    </div>
                </>
            )}

            <div className="flex flex-col gap-1.5">
                <Label htmlFor="eval-case-criteria">Evaluation criteria</Label>
                <Textarea
                    className="min-h-40"
                    disabled={saving}
                    id="eval-case-criteria"
                    onChange={(event) => {
                        onDraftChange({
                            ...draft,
                            criteria: event.target.value,
                        });
                    }}
                    value={draft.criteria}
                />
            </div>
        </div>
    );
};

export const EvalCasesPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const searchState = useSearch({ from: "/eval-cases" });
    const navigate = useNavigate({ from: "/eval-cases" });
    const {
        caseId: selectedCaseId,
        desc,
        page: currentPage,
        pageSize,
        query: searchValue,
        sortBy,
        suite,
    } = searchState;
    const [cases, setCases] = useState<EvalCaseDefinition[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | undefined>();
    const [mode, setMode] = useState<"view" | "edit" | "new">("view");
    const [draft, setDraft] = useState<EvalCaseDraft>(() => emptyDraft());
    const [draftBaseline, setDraftBaseline] = useState<EvalCaseDraft>(() =>
        emptyDraft(),
    );
    const [saving, setSaving] = useState(false);
    const [actionError, setActionError] = useState<string | undefined>();
    const [deleteTarget, setDeleteTarget] = useState<
        EvalCaseDefinition | undefined
    >();
    const [discardDialogOpen, setDiscardDialogOpen] = useState(false);

    const navigateWithSearch = useCallback(
        (
            updater: (previous: EvalCasesSearch) => Partial<EvalCasesSearch>,
            options?: { replace?: boolean },
        ): void => {
            void navigate({
                replace: options?.replace,
                search: (previous) => ({
                    ...previous,
                    ...updater(previous),
                }),
                to: "/eval-cases",
            });
        },
        [navigate],
    );

    const loadCases = useCallback(async (): Promise<void> => {
        setLoading(true);
        setError(undefined);
        try {
            const response = await fetchEvalCaseDefinitions(api, suite);
            setCases(response);
        } catch (error_) {
            setError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to load eval cases",
            );
        } finally {
            setLoading(false);
        }
    }, [api, suite]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            setMode("view");
            setDraft(emptyDraft());
            setDraftBaseline(emptyDraft());
            setActionError(undefined);
            setDiscardDialogOpen(false);
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [suite]);

    useEffect(() => {
        void loadCases();
    }, [loadCases]);

    const activeCases = useMemo(
        () => cases.filter((caseDefinition) => caseDefinition.active),
        [cases],
    );

    useEffect(() => {
        if (suite === "chatbot" && sortBy === "expected") {
            navigateWithSearch(
                () => ({
                    page: 1,
                    sortBy: "case_id",
                }),
                { replace: true },
            );
        }
    }, [navigateWithSearch, sortBy, suite]);

    useEffect(() => {
        if (mode !== "view" || loading || selectedCaseId === undefined) {
            return;
        }
        if (
            activeCases.some(
                (caseDefinition) => caseDefinition.caseId === selectedCaseId,
            )
        ) {
            return;
        }
        navigateWithSearch(() => ({ caseId: undefined }), {
            replace: true,
        });
    }, [activeCases, loading, mode, navigateWithSearch, selectedCaseId]);

    const selectedCase = useMemo(
        () =>
            selectedCaseId === undefined
                ? undefined
                : activeCases.find(
                      (caseDefinition) =>
                          caseDefinition.caseId === selectedCaseId,
                  ),
        [activeCases, selectedCaseId],
    );

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (mode !== "view") {
                return;
            }
            const nextDraft =
                selectedCase === undefined
                    ? emptyDraft()
                    : draftFromPayload(suite, selectedCase.payload);
            setDraft(nextDraft);
            setDraftBaseline(nextDraft);
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [mode, selectedCase, suite]);

    const filteredCases = useMemo(() => {
        const query = searchValue.trim().toLowerCase();
        if (query === "") {
            return activeCases;
        }
        return activeCases.filter((caseDefinition) => {
            const payload = JSON.stringify(
                caseDefinition.payload,
            ).toLowerCase();
            return (
                caseDefinition.caseId.toLowerCase().includes(query) ||
                payload.includes(query)
            );
        });
    }, [activeCases, searchValue]);

    const suiteLabel = selectedSuiteLabel(suite);
    const isEditing = mode === "edit" || mode === "new";
    const existingCase = mode !== "new";
    const canEditSelectedCase =
        mode === "view" &&
        selectedCase !== undefined &&
        selectedCase.status !== "deleted";
    const detailTitle = mode === "new" ? "New eval case" : selectedCase?.caseId;
    const showDetailHeader = detailTitle !== undefined || isEditing;
    const hasDraftChanges = isEditing && !draftsEqual(draft, draftBaseline);
    const columns = useMemo(() => buildCaseColumns(suite), [suite]);
    const effectiveSortBy =
        suite === "chatbot" && sortBy === "expected" ? "case_id" : sortBy;
    const sorting = useMemo<SortingState>(
        () => [{ desc, id: effectiveSortBy }],
        [desc, effectiveSortBy],
    );
    const pagination = useMemo<PaginationState>(
        () => ({ pageIndex: currentPage - 1, pageSize }),
        [currentPage, pageSize],
    );
    const pageCount = Math.max(1, Math.ceil(filteredCases.length / pageSize));
    const onPaginationChange: OnChangeFn<PaginationState> = (updater) => {
        const next =
            typeof updater === "function" ? updater(pagination) : updater;
        const nextPageSize = isDataTablePageSize(next.pageSize)
            ? next.pageSize
            : pageSize;
        navigateWithSearch(() => ({
            page: next.pageIndex + 1,
            pageSize: nextPageSize,
        }));
    };
    const onSortingChange: OnChangeFn<SortingState> = (updater) => {
        const next = typeof updater === "function" ? updater(sorting) : updater;
        const [nextSort] = next;
        navigateWithSearch(() => ({
            desc: nextSort?.desc ?? false,
            page: 1,
            sortBy: isEvalCasesSortBy(nextSort?.id) ? nextSort.id : "case_id",
        }));
    };

    useEffect(() => {
        if (currentPage > pageCount) {
            navigateWithSearch(() => ({ page: pageCount }), { replace: true });
        }
    }, [currentPage, navigateWithSearch, pageCount]);

    const startNewCase = (): void => {
        const nextDraft = emptyDraft();
        setMode("new");
        navigateWithSearch(() => ({ caseId: undefined }));
        setDraft(nextDraft);
        setDraftBaseline(nextDraft);
        setActionError(undefined);
    };

    const startEditCase = (): void => {
        if (selectedCase === undefined) {
            return;
        }
        const nextDraft = draftFromPayload(suite, selectedCase.payload);
        setMode("edit");
        setDraft(nextDraft);
        setDraftBaseline(nextDraft);
        setActionError(undefined);
    };

    const discardEditing = (): void => {
        setMode("view");
        setActionError(undefined);
        setDiscardDialogOpen(false);
        if (selectedCase === undefined) {
            const nextDraft = emptyDraft();
            setDraft(nextDraft);
            setDraftBaseline(nextDraft);
        } else {
            const nextDraft = draftFromPayload(suite, selectedCase.payload);
            setDraft(nextDraft);
            setDraftBaseline(nextDraft);
        }
    };

    const requestCancelEditing = (): void => {
        if (hasDraftChanges) {
            setDiscardDialogOpen(true);
            return;
        }
        discardEditing();
    };

    const handleSave = async (): Promise<void> => {
        setSaving(true);
        setActionError(undefined);
        const payload = payloadFromDraft(suite, draft);
        try {
            const saveDraft = async (): Promise<EvalCaseDefinition> => {
                if (mode === "new") {
                    return createEvalCaseDefinition(api, suite, payload);
                }
                if (selectedCase === undefined) {
                    throw new Error("Select a case before saving changes");
                }
                return updateEvalCaseDefinition(
                    api,
                    suite,
                    selectedCase.caseId,
                    payload,
                );
            };
            const saved = await saveDraft();
            const savedDraft = draftFromPayload(suite, saved.payload);
            toast.success(
                mode === "new" ? "Eval case created" : "Eval case saved",
            );
            await loadCases();
            setMode("view");
            navigateWithSearch(() => ({ caseId: saved.caseId }));
            setDraft(savedDraft);
            setDraftBaseline(savedDraft);
        } catch (error_) {
            setActionError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to save eval case",
            );
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (
        caseDefinition: EvalCaseDefinition,
    ): Promise<void> => {
        setSaving(true);
        setActionError(undefined);
        try {
            await deleteEvalCaseDefinition(api, suite, caseDefinition.caseId);
            toast.success("Eval case deleted");
            setDeleteTarget(undefined);
            setMode("view");
            navigateWithSearch(() => ({ caseId: undefined }));
            setDraft(emptyDraft());
            setDraftBaseline(emptyDraft());
            await loadCases();
        } catch (error_) {
            setActionError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to delete eval case",
            );
        } finally {
            setSaving(false);
        }
    };

    if (error !== undefined && cases.length === 0) {
        return (
            <PageError
                message={error}
                onRetry={() => void loadCases()}
            />
        );
    }

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="Eval Cases">
                <PageHeaderGroup>
                    <Select
                        onValueChange={(value) => {
                            if (value === "chatbot" || value === "guardrails") {
                                navigateWithSearch(() => ({
                                    caseId: undefined,
                                    desc: false,
                                    page: 1,
                                    query: "",
                                    sortBy: "case_id",
                                    suite: value,
                                }));
                            }
                        }}
                        value={suite}
                    >
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="Select suite">
                                {suiteLabel}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {evalSuiteOptions.map((option) => (
                                    <SelectItem
                                        key={option.value}
                                        value={option.value}
                                    >
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                    <Button
                        onClick={() => void loadCases()}
                        variant="outline"
                    >
                        <RefreshCw data-icon="inline-start" />
                        Refresh
                    </Button>
                    <Button onClick={startNewCase}>
                        <Plus data-icon="inline-start" />
                        New case
                    </Button>
                </PageHeaderGroup>
            </PageHeader>

            {error !== undefined && cases.length > 0 && (
                <PageSection>
                    <InlineError
                        message={error}
                        onRetry={() => void loadCases()}
                    />
                </PageSection>
            )}
            {actionError !== undefined && (
                <PageSection>
                    <InlineError message={actionError} />
                </PageSection>
            )}

            <PageSection className="flex min-h-0 flex-1">
                <ResizablePanelGroup
                    className="h-full min-h-0 min-w-0"
                    id="eval-cases-layout"
                    orientation="horizontal"
                    style={{ overflow: "visible" }}
                >
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        defaultSize="50%"
                        id="eval-cases-list-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        <section className="flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-hidden">
                            <Input
                                onChange={(event) => {
                                    navigateWithSearch(
                                        () => ({
                                            page: 1,
                                            query: event.target.value,
                                        }),
                                        { replace: true },
                                    );
                                }}
                                placeholder="Search..."
                                value={searchValue}
                            />
                            <DataTable
                                columns={columns}
                                data={filteredCases}
                                emptyMessage="No eval cases match the current filters."
                                isLoading={loading}
                                isRowSelected={(caseDefinition) =>
                                    mode !== "new" &&
                                    selectedCaseId === caseDefinition.caseId
                                }
                                manualPagination={false}
                                manualSorting={false}
                                onPaginationChange={onPaginationChange}
                                onRowClick={
                                    isEditing
                                        ? undefined
                                        : (caseDefinition): void => {
                                              navigateWithSearch(() => ({
                                                  caseId: caseDefinition.caseId,
                                              }));
                                              setMode("view");
                                              setActionError(undefined);
                                          }
                                }
                                onSortingChange={onSortingChange}
                                pageCount={pageCount}
                                pagination={pagination}
                                rowCount={filteredCases.length}
                                sorting={sorting}
                                tableClassName="min-w-[760px] table-fixed"
                            />
                        </section>
                    </ResizablePanel>
                    <ResizableHandle
                        className="mx-2 aria-[orientation=horizontal]:mx-0 aria-[orientation=horizontal]:my-2"
                        withHandle
                    />
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        defaultSize="50%"
                        id="eval-cases-detail-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        <section className="flex h-full min-h-0 min-w-0 flex-col gap-4 overflow-hidden">
                            {showDetailHeader && (
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        {detailTitle !== undefined && (
                                            <h2 className="text-base font-semibold">
                                                {detailTitle}
                                            </h2>
                                        )}
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        {canEditSelectedCase && (
                                            <Button
                                                onClick={startEditCase}
                                                size="sm"
                                                variant="outline"
                                            >
                                                Edit
                                            </Button>
                                        )}
                                        {isEditing && (
                                            <>
                                                <Button
                                                    disabled={saving}
                                                    onClick={() =>
                                                        void handleSave()
                                                    }
                                                    size="sm"
                                                >
                                                    <Save data-icon="inline-start" />
                                                    Save
                                                </Button>
                                                <Button
                                                    disabled={saving}
                                                    onClick={
                                                        requestCancelEditing
                                                    }
                                                    size="sm"
                                                    variant="outline"
                                                >
                                                    <X data-icon="inline-start" />
                                                    Cancel
                                                </Button>
                                            </>
                                        )}
                                    </div>
                                </div>
                            )}
                            <div className="min-h-0 min-w-0 flex-1 overflow-auto pr-1">
                                <div className="flex flex-col gap-4">
                                    {mode === "view" &&
                                    selectedCase === undefined ? (
                                        <div className="text-muted-foreground text-sm">
                                            No case selected.
                                        </div>
                                    ) : (
                                        <>
                                            <CaseForm
                                                draft={draft}
                                                editing={isEditing}
                                                existingCase={existingCase}
                                                onDraftChange={setDraft}
                                                saving={saving}
                                                suite={suite}
                                            />
                                            {mode === "view" &&
                                                selectedCase !== undefined && (
                                                    <div className="border-border flex justify-end border-t pt-4">
                                                        <Button
                                                            disabled={saving}
                                                            onClick={() => {
                                                                setDeleteTarget(
                                                                    selectedCase,
                                                                );
                                                            }}
                                                            size="sm"
                                                            variant="destructive"
                                                        >
                                                            <Trash2 data-icon="inline-start" />
                                                            Delete
                                                        </Button>
                                                    </div>
                                                )}
                                        </>
                                    )}
                                </div>
                            </div>
                        </section>
                    </ResizablePanel>
                </ResizablePanelGroup>
            </PageSection>

            <AlertDialog
                onOpenChange={setDiscardDialogOpen}
                open={discardDialogOpen}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Discard changes?</AlertDialogTitle>
                        <AlertDialogDescription>
                            Unsaved changes will be lost.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel disabled={saving}>
                            Keep editing
                        </AlertDialogCancel>
                        <AlertDialogAction
                            disabled={saving}
                            onClick={discardEditing}
                            variant="destructive"
                        >
                            Discard
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>

            <AlertDialog
                onOpenChange={(open) => {
                    if (!open) {
                        setDeleteTarget(undefined);
                    }
                }}
                open={deleteTarget !== undefined}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete eval case?</AlertDialogTitle>
                        <AlertDialogDescription>
                            This case will be removed from the active eval set.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel disabled={saving}>
                            Cancel
                        </AlertDialogCancel>
                        <AlertDialogAction
                            disabled={saving || deleteTarget === undefined}
                            onClick={() => {
                                if (deleteTarget !== undefined) {
                                    void handleDelete(deleteTarget);
                                }
                            }}
                            variant="destructive"
                        >
                            Delete
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </PageShell>
    );
};
