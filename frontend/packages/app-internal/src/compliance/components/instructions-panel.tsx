import type { ColumnDef, PaginationState } from "@tanstack/react-table";
import { ConfirmDialog } from "@va/shared/components/dialog";
import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@va/shared/components/ui/collapsible";
import { Textarea } from "@va/shared/components/ui/textarea";
import { isApiError } from "@va/shared/lib/api-client";
import { Pencil, RotateCcw, Save, X } from "lucide-react";
import { type JSX, useCallback, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
import { DataTable } from "../../components/data-table";
import { getDefaultDataTablePageSize } from "../../components/data-table-constants";
import { InlineError, LoadingState } from "../../components/page-state";
import { formatTableTimestamp } from "../../lib/date-format";
import { useComplianceData } from "../hooks/use-compliance-data";
import type {
    InstructionsDetail,
    InstructionsPage,
    InstructionsVersion,
} from "../types";
import { UnsavedChanges } from "./unsaved-changes";

interface Draft {
    content: string;
    original: string;
    baseId?: string;
}

const instructionColumns: ColumnDef<InstructionsVersion>[] = [
    { accessorKey: "number", header: "Version" },
    {
        accessorKey: "created_at",
        header: "Saved",
        cell: ({ row }) => formatTableTimestamp(row.original.created_at),
    },
    { accessorKey: "author", header: "By" },
];

export const InstructionsPanel = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const { user } = useAuth();
    const canEdit = hasPermission(user, "edit_compliance_instructions");
    const [pagination, setPagination] = useState<PaginationState>(() => ({
        pageIndex: 0,
        pageSize: getDefaultDataTablePageSize(),
    }));
    const [draft, setDraft] = useState<Draft>();
    const [saved, setSaved] = useState<InstructionsDetail>();
    const [selected, setSelected] = useState<string>();
    const [pending, setPending] = useState(false);
    const [error, setError] = useState<string>();
    const [conflict, setConflict] = useState(false);
    const [discard, setDiscard] = useState(false);
    const [restore, setRestore] = useState(false);
    const load = useCallback(
        async (signal: AbortSignal) => ({
            ...(await api.get<InstructionsPage>(
                `/compliance/instructions?offset=${pagination.pageIndex * pagination.pageSize}&limit=${pagination.pageSize}`,
                { signal },
            )),
            pagination,
        }),
        [api, pagination],
    );
    const data = useComplianceData<
        InstructionsPage & { pagination: PaginationState }
    >({
        load,
        poll: false,
        retainPreviousData: true,
        errorMessage: "Could not load the saved instructions.",
    });
    const loadSelected = useCallback(
        async (signal: AbortSignal) =>
            api.get<InstructionsDetail>(
                `/compliance/instructions/${selected ?? ""}`,
                { signal },
            ),
        [api, selected],
    );
    const historical = useComplianceData<InstructionsDetail | undefined>({
        load: loadSelected,
        enabled: selected !== undefined,
        poll: false,
        errorMessage: "Could not load this version.",
    });
    const current =
        data.data === undefined
            ? undefined
            : saved && saved.number > (data.data?.current?.number ?? 0)
              ? saved
              : (data.data?.current ?? undefined);
    const dirty = draft !== undefined && draft.content !== draft.original;
    const save = async (restoring: boolean): Promise<void> => {
        if (restoring && (historical.loading || !historical.data)) {
            return;
        }
        setPending(true);
        setError(undefined);
        try {
            const version = await api.post<InstructionsDetail>(
                "/compliance/instructions",
                restoring
                    ? {
                          base_version_id: current?.id,
                          restore_from_id: historical.data?.id,
                      }
                    : {
                          base_version_id: draft?.baseId,
                          content: draft?.content,
                      },
            );
            setSaved(version);
            setConflict(false);
            setDraft(undefined);
            setSelected(undefined);
            setRestore(false);
            setPagination((previous) =>
                previous.pageIndex === 0
                    ? previous
                    : { ...previous, pageIndex: 0 },
            );
            data.refresh();
            toast.success(
                restoring
                    ? "Restored as a new saved version. Future screenings will use it."
                    : "Instructions saved. Future screenings will use this version.",
            );
        } catch (error_) {
            if (isApiError(error_) && error_.status === 409) {
                data.refresh();
                if (draft === undefined) {
                    setError(error_.message);
                } else {
                    setConflict(true);
                    setError(undefined);
                }
            } else {
                setError(
                    error_ instanceof Error
                        ? error_.message
                        : "The instructions could not be saved. Your text is still here.",
                );
            }
        } finally {
            setPending(false);
        }
    };
    if (data.data === undefined) {
        return data.error === undefined ? (
            <LoadingState className="min-h-48" />
        ) : (
            <InlineError
                message={data.error}
                onRetry={() => {
                    data.refresh();
                }}
            />
        );
    }
    return (
        <div className="flex flex-col gap-4">
            <UnsavedChanges
                dirty={dirty}
                onDiscard={() => {
                    setConflict(false);
                    setDraft(undefined);
                }}
                pending={pending}
            />
            {data.error !== undefined && (
                <InlineError
                    message={data.error}
                    onRetry={() => {
                        data.refresh();
                    }}
                />
            )}
            {error !== undefined && (
                <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}
            {draft !== undefined && conflict && (
                <Alert>
                    <AlertDescription className="flex flex-col gap-3">
                        <p>
                            The saved instructions changed while you were editing.
                            Your draft is still here.
                        </p>
                        {current?.id === draft.baseId ? (
                            <p>Reload the latest version before continuing.</p>
                        ) : current ? (
                            <>
                                <Collapsible>
                                    <CollapsibleTrigger
                                        render={
                                            <Button
                                                pressMotion={false}
                                                size="sm"
                                                variant="ghost"
                                            />
                                        }
                                    >
                                        Review latest saved instructions (Version {current.number})
                                    </CollapsibleTrigger>
                                    <CollapsibleContent>
                                        <p className="mt-2 break-words whitespace-pre-wrap">
                                            {current.content}
                                        </p>
                                    </CollapsibleContent>
                                </Collapsible>
                                <div>
                                    <Button
                                        onClick={() => {
                                            setDraft({
                                                ...draft,
                                                baseId: current.id,
                                            });
                                            setConflict(false);
                                        }}
                                        variant="outline"
                                    >
                                        Continue with my draft
                                    </Button>
                                </div>
                            </>
                        ) : undefined}
                    </AlertDescription>
                </Alert>
            )}
            <Card size="sm">
                {(current !== undefined || (canEdit && !draft)) && (
                    <CardHeader>
                        {current && (
                            <>
                                <CardTitle>Current instructions</CardTitle>
                                <CardDescription>
                                    Version {current.number} · Saved{" "}
                                    {formatTableTimestamp(current.created_at)} by{" "}
                                    {current.author}
                                </CardDescription>
                            </>
                        )}
                        {canEdit && !draft && (
                            <CardAction>
                                <Button
                                    disabled={
                                        (!current && data.loading) ||
                                        Boolean(data.error)
                                    }
                                    onClick={() => {
                                        setConflict(false);
                                        setError(undefined);
                                        setDraft({
                                            content: current?.content ?? "",
                                            original: current?.content ?? "",
                                            baseId: current?.id,
                                        });
                                    }}
                                    size="sm"
                                    variant="outline"
                                >
                                    <Pencil data-icon="inline-start" />
                                    Edit
                                </Button>
                            </CardAction>
                        )}
                    </CardHeader>
                )}
                <CardContent>
                    {draft ? (
                        <Textarea
                            aria-label="Screening instructions"
                            className="h-64"
                            disabled={pending}
                            maxLength={30_000}
                            onChange={(event) => {
                                setDraft({
                                    ...draft,
                                    content: event.target.value,
                                });
                            }}
                            value={draft.content}
                        />
                    ) : current ? (
                        <p className="break-words whitespace-pre-wrap">
                            {current.content}
                        </p>
                    ) : (
                        <p>
                            {canEdit
                                ? "Add your team's screening requirements before starting the first screening."
                                : "Your team's instruction owner needs to add screening instructions before screenings can begin."}
                        </p>
                    )}
                </CardContent>
                {draft && (
                    <CardFooter className="flex flex-wrap gap-2">
                        <Button
                            aria-busy={pending}
                            disabled={
                                pending ||
                                conflict ||
                                !dirty ||
                                !draft.content.trim()
                            }
                            onClick={() => {
                                void save(false);
                            }}
                        >
                            <Save data-icon="inline-start" />
                            Save
                        </Button>
                        <Button
                            disabled={pending}
                            onClick={() => {
                                if (dirty) {
                                    setDiscard(true);
                                } else {
                                    setConflict(false);
                                    setDraft(undefined);
                                }
                            }}
                            variant="outline"
                        >
                            <X data-icon="inline-start" />
                            Cancel
                        </Button>
                        {pending && (
                            <LoadingState variant="inline" />
                        )}
                    </CardFooter>
                )}
            </Card>
            {!draft && data.data.total > 0 && (
                <Collapsible>
                    <CollapsibleTrigger
                        render={
                            <Button
                                pressMotion={false}
                                size="sm"
                                variant="ghost"
                            />
                        }
                    >
                        History
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <div className="mt-3 flex flex-col gap-4">
                            <div
                                aria-busy={data.loading}
                                className="flex flex-col"
                                inert={data.loading}
                            >
                                <DataTable
                                    columns={instructionColumns}
                                    data={data.data.versions}
                                    getRowActionLabel={(row) =>
                                        `Open version ${row.number}`
                                    }
                                    getRowId={(row) => row.id}
                                    isRowSelected={(row) => row.id === selected}
                                    onPaginationChange={setPagination}
                                    onRowClick={(row) => {
                                        setSelected(row.id);
                                    }}
                                    pageCount={Math.ceil(
                                        data.data.total /
                                            data.data.pagination.pageSize,
                                    )}
                                    pagination={data.data.pagination}
                                    rowCount={data.data.total}
                                    showPagination={
                                        data.data.total >
                                            data.data.pagination.pageSize ||
                                        data.data.pagination.pageIndex > 0
                                    }
                                    tableClassName="min-w-[32rem] table-fixed tabular-nums"
                                    wrapCellText
                                />
                            </div>
                            {historical.error !== undefined && (
                                <InlineError
                                    message={historical.error}
                                    onRetry={() => {
                                        historical.refresh();
                                    }}
                                />
                            )}
                            {selected !== undefined &&
                                historical.loading &&
                                historical.data === undefined && (
                                    <LoadingState className="min-h-24" />
                                )}
                            {selected !== undefined && historical.data && (
                                <Card
                                    aria-busy={historical.loading}
                                    aria-label="Selected saved instructions"
                                    inert={historical.loading}
                                    size="sm"
                                >
                                    <CardHeader>
                                        <CardTitle>
                                            Version {historical.data.number}
                                        </CardTitle>
                                        <CardDescription>
                                            Saved{" "}
                                            {formatTableTimestamp(
                                                historical.data.created_at,
                                            )}{" "}
                                            by {historical.data.author}
                                        </CardDescription>
                                        {canEdit && (
                                            <CardAction>
                                                <Button
                                                    disabled={
                                                        historical.loading ||
                                                        pending ||
                                                        historical.data.id ===
                                                            current?.id
                                                    }
                                                    onClick={() => {
                                                        setRestore(true);
                                                    }}
                                                    size="sm"
                                                    variant="outline"
                                                >
                                                    <RotateCcw data-icon="inline-start" />
                                                    Restore as a new version
                                                </Button>
                                            </CardAction>
                                        )}
                                    </CardHeader>
                                    <CardContent className="flex flex-col gap-3">
                                        {pending && (
                                            <LoadingState variant="inline" />
                                        )}
                                        <p className="break-words whitespace-pre-wrap">
                                            {historical.data.content}
                                        </p>
                                    </CardContent>
                                </Card>
                            )}
                        </div>
                    </CollapsibleContent>
                </Collapsible>
            )}
            <ConfirmDialog
                confirmLabel="Discard"
                description="Your saved instructions will stay unchanged."
                onConfirm={() => {
                    setConflict(false);
                    setDraft(undefined);
                }}
                onOpenChange={setDiscard}
                open={discard}
                title="Discard unsaved instructions?"
            />
            <ConfirmDialog
                confirmLabel="Restore as new version"
                description="A new saved version will be created. Running and completed screenings will keep the instructions they already used."
                onConfirm={async () => save(true)}
                onOpenChange={setRestore}
                open={restore}
                title="Use these instructions for future screenings?"
            />
        </div>
    );
};
