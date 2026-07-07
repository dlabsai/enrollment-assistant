import { useNavigate, useSearch } from "@tanstack/react-router";
import type {
    ColumnDef,
    OnChangeFn,
    PaginationState,
    SortingState,
} from "@tanstack/react-table";
import { Streamdown } from "@va/shared/components/streamdown";
import {
    Alert,
    AlertDescription,
    AlertTitle,
} from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@va/shared/components/ui/collapsible";
import { Input } from "@va/shared/components/ui/input";
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
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "@va/shared/components/ui/tabs";
import { handleFetchError } from "@va/shared/lib/api-client";
import {
    CheckCircle2,
    CircleMinus,
    Copy,
    ExternalLink,
    FileText,
    Folder,
    FolderOpen,
    RefreshCw,
} from "lucide-react";
import {
    type JSX,
    memo,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { DataTable } from "../../components/data-table";
import { isDataTablePageSize } from "../../components/data-table-constants";
import { PageHeader } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError, LoadingState } from "../../components/page-state";
import {
    excludeRagDocument,
    fetchRagDocument,
    fetchRagDocumentExclusionEvents,
    fetchRagDocuments,
    fetchRagDocumentTree,
    includeRagDocument,
} from "../../rag-viewer/lib/api";
import {
    formatNumber,
    getSourceTypesForFilter,
    LARGE_MARKDOWN_RENDER_CHARACTER_THRESHOLD,
} from "../../rag-viewer/lib/viewer-utils";
import type {
    RagDocumentDetailData,
    RagDocumentExclusionEvent,
    RagDocumentSummary,
    RagDocumentTreeNode,
    RagSourceType,
} from "../../rag-viewer/types";
import {
    defaultRagExclusionsDescending,
    defaultRagExclusionsSortBy,
    isRagExclusionsHistorySortBy,
    isRagExclusionsListSortBy,
    type RagExclusionsSearch,
} from "../lib/search-state";

const CONTENT_STATUS_FILTER_OPTIONS: {
    label: string;
    value: RagExclusionsSearch["exclusion"];
}[] = [
    { label: "All statuses", value: "all" },
    { label: "Included", value: "included" },
    { label: "Excluded", value: "excluded" },
];

const HISTORY_STATUS_FILTER_OPTIONS: {
    label: string;
    value: RagExclusionsSearch["exclusion"];
}[] = [
    { label: "All changes", value: "all" },
    { label: "Include", value: "included" },
    { label: "Exclude", value: "excluded" },
];

const KNOWLEDGE_CONTROL_SOURCE_TYPES: RagSourceType[] = [
    "website_page",
    "website_program",
    "catalog_page",
    "catalog_program",
    "catalog_course",
    "training_material",
];

const CONTENT_SOURCE_FILTER_OPTIONS: {
    label: string;
    value: RagExclusionsSearch["source"];
}[] = [
    { label: "All document types", value: "all" },
    { label: "Website", value: "website" },
    { label: "Catalog", value: "catalog" },
    { label: "Training materials", value: "training" },
    { label: "Website pages", value: "website_page" },
    { label: "Website program pages", value: "website_program" },
    { label: "Catalog pages", value: "catalog_page" },
    { label: "Catalog programs", value: "catalog_program" },
    { label: "Catalog courses", value: "catalog_course" },
    { label: "Training files", value: "training_material" },
];

const VISIBILITY_TOAST_OPTIONS = { position: "top-center" } as const;
const HISTORY_DATE_TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
});

const getStatusFilterLabel = (
    value: RagExclusionsSearch["exclusion"],
    view: RagExclusionsSearch["view"],
): string => {
    const options =
        view === "history"
            ? HISTORY_STATUS_FILTER_OPTIONS
            : CONTENT_STATUS_FILTER_OPTIONS;
    return options.find((option) => option.value === value)?.label ?? value;
};

const getSourceFilterLabel = (value: RagExclusionsSearch["source"]): string =>
    CONTENT_SOURCE_FILTER_OPTIONS.find((option) => option.value === value)
        ?.label ?? value;

const getFriendlySourceLabel = (
    sourceType: RagDocumentSummary["source_type"],
): string => {
    switch (sourceType) {
        case "website_page": {
            return "Website page";
        }
        case "website_program": {
            return "Website program page";
        }
        case "catalog_page": {
            return "Catalog page";
        }
        case "catalog_program": {
            return "Catalog program";
        }
        case "catalog_course": {
            return "Catalog course";
        }
        case "training_material": {
            return "Training file";
        }
        default: {
            const exhaustiveCheck: never = sourceType;
            return exhaustiveCheck;
        }
    }
};

const getFriendlyTreeLabel = (node: RagDocumentTreeNode): string => {
    switch (node.label) {
        case "Website": {
            return "Website";
        }
        case "Website pages": {
            return "Website pages";
        }
        case "Website programs": {
            return "Website program pages";
        }
        case "Catalog": {
            return "Catalog";
        }
        case "Training materials": {
            return "Training materials";
        }
        default: {
            return node.label;
        }
    }
};

const getKnowledgeControlSourceTypesForFilter = (
    sourceFilter: RagExclusionsSearch["source"],
): RagSourceType[] =>
    sourceFilter === "all"
        ? KNOWLEDGE_CONTROL_SOURCE_TYPES
        : (getSourceTypesForFilter(sourceFilter) ??
          KNOWLEDGE_CONTROL_SOURCE_TYPES);

const filterDocumentTree = (
    nodes: RagDocumentTreeNode[],
    sourceFilter: RagExclusionsSearch["source"],
    query: string,
): RagDocumentTreeNode[] => {
    const allowedSourceTypes =
        getKnowledgeControlSourceTypesForFilter(sourceFilter);
    const normalizedQuery = query.trim().toLocaleLowerCase();

    const filterNode = (
        node: RagDocumentTreeNode,
        ancestorMatchesQuery: boolean,
    ): RagDocumentTreeNode | undefined => {
        const nodeMatchesQuery =
            normalizedQuery === "" ||
            getFriendlyTreeLabel(node)
                .toLocaleLowerCase()
                .includes(normalizedQuery);

        if (node.document_id !== null) {
            const typeMatches =
                node.source_type !== null &&
                allowedSourceTypes.includes(node.source_type);
            const searchMatches =
                normalizedQuery === "" ||
                ancestorMatchesQuery ||
                nodeMatchesQuery;

            return typeMatches && searchMatches ? node : undefined;
        }

        const childAncestorMatchesQuery =
            ancestorMatchesQuery ||
            (normalizedQuery !== "" && nodeMatchesQuery);
        const children = node.children
            .map((child) => filterNode(child, childAncestorMatchesQuery))
            .filter(
                (child): child is RagDocumentTreeNode => child !== undefined,
            );

        return children.length > 0 ? { ...node, children } : undefined;
    };

    return nodes
        .map((node) => filterNode(node, false))
        .filter((node): node is RagDocumentTreeNode => node !== undefined);
};

const buildTreeDocumentCounts = (
    nodes: RagDocumentTreeNode[],
): Record<string, number> => {
    const counts: Record<string, number> = {};

    const countNode = (node: RagDocumentTreeNode): number => {
        const count =
            node.document_id === null
                ? node.children.reduce(
                      (total, child) => total + countNode(child),
                      0,
                  )
                : 1;
        counts[node.id] = count;
        return count;
    };

    for (const node of nodes) {
        countNode(node);
    }

    return counts;
};

const collectDefaultOpenTreeNodeIds = (
    nodes: RagDocumentTreeNode[],
    depth = 0,
): Set<string> => {
    const openNodeIds = new Set<string>();

    for (const node of nodes) {
        if (node.children.length > 0) {
            if (depth <= 1) {
                openNodeIds.add(node.id);
            }

            for (const childId of collectDefaultOpenTreeNodeIds(
                node.children,
                depth + 1,
            )) {
                openNodeIds.add(childId);
            }
        }
    }

    return openNodeIds;
};

const statusText = (excluded: boolean): string =>
    excluded ? "Excluded" : "Included";

const historyActionText = (
    action: RagDocumentExclusionEvent["action"],
): string => (action === "excluded" ? "Exclude" : "Include");

const formatHistoryTimestamp = (value: string): string => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }
    return HISTORY_DATE_TIME_FORMATTER.format(date);
};

const formatHistoryActor = (event: RagDocumentExclusionEvent): string =>
    event.actor_name ?? event.actor_email ?? "Unknown user";

const contentColumns: ColumnDef<RagDocumentSummary>[] = [
    {
        id: "title",
        accessorKey: "title",
        header: "Name",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="font-medium break-words">
                {row.original.title}
            </span>
        ),
    },
    {
        id: "source_type",
        accessorFn: (document) => getFriendlySourceLabel(document.source_type),
        header: "Type",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {getFriendlySourceLabel(row.original.source_type)}
            </span>
        ),
    },
    {
        id: "excluded",
        accessorFn: (document) => statusText(document.excluded),
        header: "Status",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs">
                {statusText(row.original.excluded)}
            </span>
        ),
    },
    {
        id: "source_id",
        accessorKey: "source_id",
        header: "ID",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words tabular-nums">
                {row.original.source_id}
            </span>
        ),
    },
];

const historyColumns: ColumnDef<RagDocumentExclusionEvent>[] = [
    {
        id: "document_title",
        accessorFn: (event) =>
            event.document_title ?? "Document no longer available",
        header: "Name",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="font-medium break-words">
                {row.original.document_title ?? "Document no longer available"}
            </span>
        ),
    },
    {
        id: "source_type",
        accessorFn: (event) =>
            event.source_type === null
                ? "Source unavailable"
                : getFriendlySourceLabel(event.source_type),
        header: "Type",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {row.original.source_type === null
                    ? "Source unavailable"
                    : getFriendlySourceLabel(row.original.source_type)}
            </span>
        ),
    },
    {
        id: "action",
        accessorKey: "action",
        header: "Change",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs">
                {historyActionText(row.original.action)}
            </span>
        ),
    },
    {
        id: "actor",
        accessorFn: formatHistoryActor,
        header: "By",
        enableSorting: true,
        cell: ({ row }) => (
            <div className="flex flex-col gap-1 text-xs">
                <span>{formatHistoryActor(row.original)}</span>
                {row.original.actor_name !== null &&
                row.original.actor_email !== null ? (
                    <span className="text-muted-foreground">
                        {row.original.actor_email}
                    </span>
                ) : null}
            </div>
        ),
    },
    {
        id: "created_at",
        accessorKey: "created_at",
        header: "When",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs">
                {formatHistoryTimestamp(row.original.created_at)}
            </span>
        ),
    },
];

interface ContentFolderTreeProps {
    documentCountsByNodeId: Record<string, number>;
    nodes: RagDocumentTreeNode[];
    onNodeOpenChange: (nodeId: string, open: boolean) => void;
    onSelectDocument: (documentId: string) => void;
    openNodeIds: Set<string>;
}

const ContentFolderTree = memo(
    ({
        documentCountsByNodeId,
        nodes,
        onNodeOpenChange,
        onSelectDocument,
        openNodeIds,
    }: ContentFolderTreeProps): JSX.Element => {
        const renderNodes = (
            treeNodes: RagDocumentTreeNode[],
            depth: number,
        ): JSX.Element[] =>
            treeNodes.map((node) => {
                const isFolder = node.children.length > 0;
                const isOpen = openNodeIds.has(node.id);
                const label = getFriendlyTreeLabel(node);

                if (!isFolder) {
                    return (
                        <button
                            className="hover:bg-muted/70 focus:bg-muted focus:ring-primary/20 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm focus:ring-1 focus:outline-none"
                            key={node.id}
                            onClick={() => {
                                if (node.document_id !== null) {
                                    onSelectDocument(node.document_id);
                                }
                            }}
                            style={{ paddingLeft: `${depth * 16 + 8}px` }}
                            type="button"
                        >
                            <FileText className="text-muted-foreground size-4 shrink-0" />
                            <span className="min-w-0 flex-1 truncate">
                                {label}
                            </span>
                            {node.excluded ? (
                                <span className="text-muted-foreground shrink-0 text-xs">
                                    Excluded
                                </span>
                            ) : null}
                        </button>
                    );
                }

                return (
                    <Collapsible
                        key={node.id}
                        onOpenChange={(open) => {
                            onNodeOpenChange(node.id, open);
                        }}
                        open={isOpen}
                    >
                        <CollapsibleTrigger
                            className="hover:bg-muted/70 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm font-medium"
                            style={{ paddingLeft: `${depth * 16 + 8}px` }}
                        >
                            {isOpen ? (
                                <FolderOpen className="text-muted-foreground size-4 shrink-0" />
                            ) : (
                                <Folder className="text-muted-foreground size-4 shrink-0" />
                            )}
                            <span className="min-w-0 flex-1 truncate">
                                {label}
                            </span>
                            <span className="text-muted-foreground shrink-0 text-xs">
                                {formatNumber(
                                    documentCountsByNodeId[node.id] ?? 0,
                                )}
                            </span>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                            {renderNodes(node.children, depth + 1)}
                        </CollapsibleContent>
                    </Collapsible>
                );
            });

        return (
            <div className="flex flex-col gap-1">{renderNodes(nodes, 0)}</div>
        );
    },
);

ContentFolderTree.displayName = "ContentFolderTree";

const copySourceUrl = async (url: string): Promise<void> => {
    try {
        await navigator.clipboard.writeText(url);
        toast.success("Source link copied");
    } catch {
        toast.error("Could not copy the source link");
    }
};

interface ContentDetailPanelProps {
    detailError: string | undefined;
    isDetailLoading: boolean;
    onInclude: (document: RagDocumentSummary) => void;
    onApproveLargeDocumentRender: (documentId: string) => void;
    onCopyUrl: (url: string) => void;
    onExclude: (document: RagDocumentSummary) => void;
    selectedDocumentId: string | undefined;
    selectedDetail: RagDocumentDetailData | undefined;
    selectedSummary: RagDocumentSummary | undefined;
    savingSourceKey: string | undefined;
    shouldGuardRender: boolean;
}

const ContentDetailPanel = ({
    detailError,
    isDetailLoading,
    onInclude,
    onApproveLargeDocumentRender,
    onCopyUrl,
    onExclude,
    selectedDocumentId,
    selectedDetail,
    selectedSummary,
    savingSourceKey,
    shouldGuardRender,
}: ContentDetailPanelProps): JSX.Element => {
    const actionDocument = selectedDetail ?? selectedSummary;
    const displayDocument = selectedDetail ?? selectedSummary;
    const isSaving =
        actionDocument !== undefined &&
        savingSourceKey === actionDocument.source_key;

    return (
        <section className="flex h-full min-h-0 min-w-0 flex-col">
            {selectedDocumentId === undefined ? (
                <div className="text-muted-foreground text-sm">
                    No document selected.
                </div>
            ) : isDetailLoading && selectedDetail === undefined ? (
                <LoadingState className="min-h-40 text-sm" />
            ) : (
                <>
                    {displayDocument !== undefined && (
                        <div className="flex flex-col gap-2 pb-3">
                            <div className="flex min-w-0 flex-col gap-2">
                                <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                                    <h2 className="min-w-0 flex-1 text-base font-medium break-words">
                                        {displayDocument.title}
                                    </h2>
                                    {actionDocument === undefined ? null : (
                                        <span className="text-muted-foreground text-sm">
                                            {statusText(
                                                actionDocument.excluded,
                                            )}
                                        </span>
                                    )}
                                </div>
                                <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                                    <span>
                                        {getFriendlySourceLabel(
                                            displayDocument.source_type,
                                        )}
                                    </span>
                                </div>
                            </div>
                            {selectedDetail !== undefined && (
                                <div className="min-w-0">
                                    <div className="grid max-w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                                        <a
                                            className="text-primary inline-flex min-w-0 flex-1 items-center gap-1 hover:underline"
                                            href={selectedDetail.url}
                                            rel="noreferrer"
                                            target="_blank"
                                        >
                                            <span className="min-w-0 flex-1 truncate text-left">
                                                {selectedDetail.url}
                                            </span>
                                            <ExternalLink className="size-3 shrink-0" />
                                        </a>
                                        <Button
                                            aria-label="Copy source link"
                                            onClick={() => {
                                                onCopyUrl(selectedDetail.url);
                                            }}
                                            size="icon-sm"
                                            type="button"
                                            variant="outline"
                                        >
                                            <Copy />
                                        </Button>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
                        {detailError !== undefined && (
                            <InlineError message={detailError} />
                        )}

                        {selectedDetail === undefined ? (
                            <div className="text-muted-foreground text-sm">
                                Unable to load this document.
                            </div>
                        ) : (
                            <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto border-t pt-3">
                                {shouldGuardRender ? (
                                    <div className="flex flex-col gap-4">
                                        <Alert>
                                            <AlertTitle>
                                                Large document
                                            </AlertTitle>
                                            <AlertDescription>
                                                This document is large, so
                                                formatting the preview may take
                                                a moment.
                                            </AlertDescription>
                                        </Alert>
                                        <div>
                                            <Button
                                                onClick={() => {
                                                    onApproveLargeDocumentRender(
                                                        selectedDetail.id,
                                                    );
                                                }}
                                                size="sm"
                                                type="button"
                                            >
                                                Show formatted preview
                                            </Button>
                                        </div>
                                        <pre className="text-foreground text-xs leading-relaxed break-words whitespace-pre-wrap">
                                            {selectedDetail.markdown_content}
                                        </pre>
                                    </div>
                                ) : (
                                    <Streamdown className="max-w-none break-words">
                                        {selectedDetail.markdown_content}
                                    </Streamdown>
                                )}
                            </div>
                        )}
                    </div>
                    {actionDocument !== undefined && (
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t pt-3">
                            <div className="text-muted-foreground text-xs">
                                Excluding a document stops the assistant from
                                using it in answers. It does not delete the
                                document.
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                {actionDocument.excluded ? (
                                    <Button
                                        disabled={isSaving}
                                        onClick={() => {
                                            onInclude(actionDocument);
                                        }}
                                        type="button"
                                    >
                                        <CheckCircle2 data-icon="inline-start" />
                                        Include
                                    </Button>
                                ) : (
                                    <Button
                                        disabled={isSaving}
                                        onClick={() => {
                                            onExclude(actionDocument);
                                        }}
                                        type="button"
                                        variant="destructive"
                                    >
                                        <CircleMinus data-icon="inline-start" />
                                        Exclude
                                    </Button>
                                )}
                            </div>
                        </div>
                    )}
                </>
            )}
        </section>
    );
};

export const RagExclusionsPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const searchState = useSearch({ from: "/rag-exclusions" });
    const navigate = useNavigate({ from: "/rag-exclusions" });
    const {
        document: selectedDocumentId,
        desc: descending,
        exclusion: exclusionFilter,
        page: currentPage,
        pageSize,
        query,
        sortBy,
        source: sourceFilter,
        view,
    } = searchState;

    const [documents, setDocuments] = useState<RagDocumentSummary[]>([]);
    const [historyEvents, setHistoryEvents] = useState<
        RagDocumentExclusionEvent[]
    >([]);
    const [documentTree, setDocumentTree] = useState<RagDocumentTreeNode[]>([]);
    const [openTreeNodeIds, setOpenTreeNodeIds] = useState<Set<string>>(
        () => new Set(),
    );
    const [total, setTotal] = useState(0);
    const [historyTotal, setHistoryTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [treeLoading, setTreeLoading] = useState(false);
    const [detailLoading, setDetailLoading] = useState(false);
    const [error, setError] = useState<string | undefined>();
    const [historyError, setHistoryError] = useState<string | undefined>();
    const [treeError, setTreeError] = useState<string | undefined>();
    const [detailError, setDetailError] = useState<string | undefined>();
    const [selectedDetail, setSelectedDetail] = useState<
        RagDocumentDetailData | undefined
    >();
    const [pendingSelectedDocumentId, setPendingSelectedDocumentId] = useState<
        string | undefined
    >();
    const [selectedHistoryEventId, setSelectedHistoryEventId] = useState<
        string | undefined
    >();
    const [savingSourceKey, setSavingSourceKey] = useState<
        string | undefined
    >();
    const [refreshCount, setRefreshCount] = useState(0);
    const [
        largeDocumentsApprovedForRender,
        setLargeDocumentsApprovedForRender,
    ] = useState<Set<string>>(() => new Set());
    const searchDebounceTimeoutRef = useRef<number | undefined>(undefined);
    const [queryInputState, setQueryInputState] = useState(() => ({
        syncedQuery: query,
        value: query,
    }));

    const queryInput =
        queryInputState.syncedQuery === query ? queryInputState.value : query;
    const offset = (currentPage - 1) * pageSize;
    const pagedTotal = view === "history" ? historyTotal : total;
    const pageCount = Math.max(1, Math.ceil(pagedTotal / pageSize));
    const statusFilterOptions =
        view === "history"
            ? HISTORY_STATUS_FILTER_OPTIONS
            : CONTENT_STATUS_FILTER_OPTIONS;
    const selectedStatusFilterLabel = getStatusFilterLabel(
        exclusionFilter,
        view,
    );
    const selectedSourceFilterLabel = getSourceFilterLabel(sourceFilter);
    const hasPendingSelection =
        pendingSelectedDocumentId !== undefined &&
        pendingSelectedDocumentId !== selectedDocumentId;
    const effectiveSelectedDocumentId = hasPendingSelection
        ? pendingSelectedDocumentId
        : selectedDocumentId;
    const currentSelectedDetail =
        selectedDetail?.id === effectiveSelectedDocumentId
            ? selectedDetail
            : undefined;
    const selectedSummary =
        documents.find(
            (document) => document.id === effectiveSelectedDocumentId,
        ) ?? currentSelectedDetail;
    const filteredDocumentTree = useMemo(
        () => filterDocumentTree(documentTree, sourceFilter, query),
        [documentTree, query, sourceFilter],
    );
    const documentCountsByTreeNodeId = useMemo(
        () => buildTreeDocumentCounts(filteredDocumentTree),
        [filteredDocumentTree],
    );
    const isSelectedDetailPending =
        effectiveSelectedDocumentId !== undefined &&
        detailError === undefined &&
        currentSelectedDetail === undefined;
    const shouldGuardSelectedDocumentRender =
        currentSelectedDetail !== undefined &&
        currentSelectedDetail.character_count >
            LARGE_MARKDOWN_RENDER_CHARACTER_THRESHOLD &&
        !largeDocumentsApprovedForRender.has(currentSelectedDetail.id);

    const navigateWithSearch = useCallback(
        (
            updater: (
                previous: RagExclusionsSearch,
            ) => Partial<RagExclusionsSearch>,
            options?: { replace?: boolean },
        ): void => {
            void navigate({
                replace: options?.replace,
                search: (previous) => ({
                    ...previous,
                    ...updater(previous),
                }),
                to: "/rag-exclusions",
            });
        },
        [navigate],
    );

    useEffect(
        () => (): void => {
            if (searchDebounceTimeoutRef.current !== undefined) {
                window.clearTimeout(searchDebounceTimeoutRef.current);
            }
        },
        [],
    );

    useEffect(() => {
        let isActive = true;

        if (view !== "list") {
            return (): void => {
                isActive = false;
            };
        }

        const loadDocuments = async (): Promise<void> => {
            setLoading(true);
            setError(undefined);

            try {
                const response = await fetchRagDocuments(api, {
                    descending,
                    exclusion: exclusionFilter,
                    limit: pageSize,
                    offset,
                    search: query,
                    searchMode: "exact",
                    sortBy: isRagExclusionsListSortBy(sortBy)
                        ? sortBy
                        : "title",
                    types: getKnowledgeControlSourceTypesForFilter(
                        sourceFilter,
                    ),
                });

                if (!isActive) {
                    return;
                }

                setDocuments(response.items);
                setTotal(response.total);
            } catch (error_: unknown) {
                if (!isActive) {
                    return;
                }

                setError(handleFetchError(error_, "Loading documents"));
                setDocuments([]);
                setTotal(0);
            } finally {
                if (isActive) {
                    setLoading(false);
                }
            }
        };

        void loadDocuments();

        return (): void => {
            isActive = false;
        };
    }, [
        api,
        descending,
        exclusionFilter,
        offset,
        pageSize,
        query,
        refreshCount,
        sortBy,
        sourceFilter,
        view,
    ]);

    useEffect(() => {
        let isActive = true;

        if (view !== "history") {
            return (): void => {
                isActive = false;
            };
        }

        const loadHistoryEvents = async (): Promise<void> => {
            setHistoryLoading(true);
            setHistoryError(undefined);

            try {
                const response = await fetchRagDocumentExclusionEvents(api, {
                    action: exclusionFilter,
                    descending,
                    limit: pageSize,
                    offset,
                    search: query,
                    sortBy: isRagExclusionsHistorySortBy(sortBy)
                        ? sortBy
                        : "created_at",
                    types: getSourceTypesForFilter(sourceFilter),
                });

                if (!isActive) {
                    return;
                }

                setHistoryEvents(response.items);
                setHistoryTotal(response.total);
            } catch (error_: unknown) {
                if (!isActive) {
                    return;
                }

                setHistoryError(handleFetchError(error_, "Loading history"));
                setHistoryEvents([]);
                setHistoryTotal(0);
            } finally {
                if (isActive) {
                    setHistoryLoading(false);
                }
            }
        };

        void loadHistoryEvents();

        return (): void => {
            isActive = false;
        };
    }, [
        api,
        descending,
        exclusionFilter,
        offset,
        pageSize,
        query,
        refreshCount,
        sortBy,
        sourceFilter,
        view,
    ]);

    useEffect(() => {
        let isActive = true;

        if (view !== "folders") {
            return (): void => {
                isActive = false;
            };
        }

        const loadTree = async (): Promise<void> => {
            setTreeLoading(true);
            setTreeError(undefined);

            try {
                const response = await fetchRagDocumentTree(
                    api,
                    exclusionFilter,
                );
                if (!isActive) {
                    return;
                }

                setDocumentTree(response);
                setOpenTreeNodeIds(collectDefaultOpenTreeNodeIds(response));
            } catch (error_: unknown) {
                if (!isActive) {
                    return;
                }

                setTreeError(handleFetchError(error_, "Loading document tree"));
                setDocumentTree([]);
                setOpenTreeNodeIds(new Set());
            } finally {
                if (isActive) {
                    setTreeLoading(false);
                }
            }
        };

        void loadTree();

        return (): void => {
            isActive = false;
        };
    }, [api, exclusionFilter, refreshCount, view]);

    useEffect(() => {
        const isPagedView = view === "list" || view === "history";
        const isPagedViewLoading =
            view === "history" ? historyLoading : loading;
        if (isPagedView && !isPagedViewLoading && currentPage > pageCount) {
            navigateWithSearch(
                () => ({
                    page: pageCount,
                }),
                { replace: true },
            );
        }
    }, [
        currentPage,
        historyLoading,
        loading,
        navigateWithSearch,
        pageCount,
        view,
    ]);

    useEffect(() => {
        let isActive = true;

        if (effectiveSelectedDocumentId !== undefined) {
            const loadDetail = async (): Promise<void> => {
                setDetailLoading(true);
                setDetailError(undefined);

                try {
                    const response = await fetchRagDocument(
                        api,
                        effectiveSelectedDocumentId,
                    );
                    if (!isActive) {
                        return;
                    }

                    setSelectedDetail(response);
                } catch (error_: unknown) {
                    if (!isActive) {
                        return;
                    }

                    setSelectedDetail(undefined);
                    setDetailError(
                        handleFetchError(error_, "Loading document preview"),
                    );
                } finally {
                    if (isActive) {
                        setDetailLoading(false);
                    }
                }
            };

            void loadDetail();
        }

        return (): void => {
            isActive = false;
        };
    }, [api, effectiveSelectedDocumentId, refreshCount]);

    const includeDocument = useCallback(
        async (document: RagDocumentSummary): Promise<void> => {
            setSavingSourceKey(document.source_key);
            try {
                await includeRagDocument(api, document.source_key);
                toast.success("Document included", VISIBILITY_TOAST_OPTIONS);
                setRefreshCount((current) => current + 1);
            } catch (error_) {
                toast.error(
                    handleFetchError(error_, "Updating document status"),
                    VISIBILITY_TOAST_OPTIONS,
                );
            } finally {
                setSavingSourceKey(undefined);
            }
        },
        [api],
    );

    const excludeDocument = useCallback(
        async (document: RagDocumentSummary): Promise<void> => {
            setSavingSourceKey(document.source_key);
            try {
                await excludeRagDocument(api, {
                    reason: "Manual exclusion",
                    source_key: document.source_key,
                });
                toast.success("Document excluded", VISIBILITY_TOAST_OPTIONS);
                setRefreshCount((current) => current + 1);
            } catch (error_) {
                toast.error(
                    handleFetchError(error_, "Updating document status"),
                    VISIBILITY_TOAST_OPTIONS,
                );
            } finally {
                setSavingSourceKey(undefined);
            }
        },
        [api],
    );

    const handleSelectDocument = useCallback(
        (documentId: string, historyEventId?: string): void => {
            setSelectedHistoryEventId(historyEventId);

            if (documentId === effectiveSelectedDocumentId) {
                if (currentSelectedDetail !== undefined || detailLoading) {
                    return;
                }

                setDetailLoading(true);
                setDetailError(undefined);
                setRefreshCount((current) => current + 1);
                return;
            }

            setPendingSelectedDocumentId(documentId);
            setDetailLoading(true);
            setDetailError(undefined);
            setSelectedDetail(undefined);

            void Promise.resolve(
                navigate({
                    search: (previous) => ({
                        ...previous,
                        document: documentId,
                    }),
                    to: "/rag-exclusions",
                }),
            ).finally(() => {
                setPendingSelectedDocumentId((current) =>
                    current === documentId ? undefined : current,
                );
            });
        },
        [
            currentSelectedDetail,
            detailLoading,
            effectiveSelectedDocumentId,
            navigate,
        ],
    );

    const handleTreeNodeOpenChange = useCallback(
        (nodeId: string, open: boolean): void => {
            setOpenTreeNodeIds((current) => {
                const next = new Set(current);
                if (open) {
                    next.add(nodeId);
                } else {
                    next.delete(nodeId);
                }
                return next;
            });
        },
        [],
    );

    const pagination = useMemo<PaginationState>(
        () => ({ pageIndex: currentPage - 1, pageSize }),
        [currentPage, pageSize],
    );
    const effectiveSortBy =
        view === "history"
            ? isRagExclusionsHistorySortBy(sortBy)
                ? sortBy
                : "created_at"
            : isRagExclusionsListSortBy(sortBy)
              ? sortBy
              : "title";
    const sorting = useMemo<SortingState>(
        () => [{ desc: descending, id: effectiveSortBy }],
        [descending, effectiveSortBy],
    );
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
        const defaultSortBy = defaultRagExclusionsSortBy(view);
        const sortId = nextSort?.id;
        const nextSortBy =
            view === "history"
                ? isRagExclusionsHistorySortBy(sortId)
                    ? sortId
                    : defaultSortBy
                : isRagExclusionsListSortBy(sortId)
                  ? sortId
                  : defaultSortBy;
        navigateWithSearch(() => ({
            desc: nextSort?.desc ?? defaultRagExclusionsDescending(view),
            page: 1,
            sortBy: nextSortBy,
        }));
    };

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="KB Controls">
                <Button
                    onClick={() => {
                        setRefreshCount((current) => current + 1);
                    }}
                    type="button"
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>
            <PageSection className="flex min-h-0 flex-1">
                <ResizablePanelGroup
                    className="h-full min-h-0 min-w-0"
                    id="rag-exclusions-layout"
                    orientation="horizontal"
                    style={{ overflow: "visible" }}
                >
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        defaultSize="50%"
                        id="rag-exclusions-list-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        <section className="flex h-full min-h-0 min-w-0 flex-col">
                            <Tabs
                                className="min-h-0 flex-1 gap-4"
                                onValueChange={(value: string) => {
                                    if (
                                        value === "list" ||
                                        value === "folders" ||
                                        value === "history"
                                    ) {
                                        navigateWithSearch(() => ({
                                            desc: defaultRagExclusionsDescending(
                                                value,
                                            ),
                                            page: 1,
                                            sortBy: defaultRagExclusionsSortBy(
                                                value,
                                            ),
                                            view: value,
                                        }));
                                    }
                                }}
                                value={view}
                            >
                                <TabsList>
                                    <TabsTrigger value="list">List</TabsTrigger>
                                    <TabsTrigger value="folders">
                                        Folders
                                    </TabsTrigger>
                                    <TabsTrigger value="history">
                                        History
                                    </TabsTrigger>
                                </TabsList>
                                <div className="flex flex-wrap items-center gap-3">
                                    <Input
                                        className="min-w-64 flex-1"
                                        onChange={(event) => {
                                            const nextQueryValue =
                                                event.target.value;
                                            setQueryInputState({
                                                syncedQuery: query,
                                                value: nextQueryValue,
                                            });

                                            if (
                                                searchDebounceTimeoutRef.current !==
                                                undefined
                                            ) {
                                                window.clearTimeout(
                                                    searchDebounceTimeoutRef.current,
                                                );
                                            }

                                            searchDebounceTimeoutRef.current =
                                                window.setTimeout((): void => {
                                                    const nextQuery =
                                                        nextQueryValue.trim();
                                                    if (nextQuery === query) {
                                                        return;
                                                    }

                                                    navigateWithSearch(
                                                        () => ({
                                                            document: undefined,
                                                            page: 1,
                                                            query: nextQuery,
                                                        }),
                                                        {
                                                            replace: true,
                                                        },
                                                    );
                                                }, 300);
                                        }}
                                        placeholder="Search..."
                                        value={queryInput}
                                    />
                                    <Select
                                        onValueChange={(value) => {
                                            const option =
                                                statusFilterOptions.find(
                                                    (item) =>
                                                        item.value === value,
                                                );
                                            if (option !== undefined) {
                                                navigateWithSearch(() => ({
                                                    document: undefined,
                                                    exclusion: option.value,
                                                    page: 1,
                                                }));
                                            }
                                        }}
                                        value={exclusionFilter}
                                    >
                                        <SelectTrigger
                                            aria-label="Status filter"
                                            className="w-[140px]"
                                        >
                                            <SelectValue>
                                                {selectedStatusFilterLabel}
                                            </SelectValue>
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectGroup>
                                                {statusFilterOptions.map(
                                                    (option) => (
                                                        <SelectItem
                                                            key={option.value}
                                                            value={option.value}
                                                        >
                                                            {option.label}
                                                        </SelectItem>
                                                    ),
                                                )}
                                            </SelectGroup>
                                        </SelectContent>
                                    </Select>
                                    <Select
                                        onValueChange={(value) => {
                                            const option =
                                                CONTENT_SOURCE_FILTER_OPTIONS.find(
                                                    (item) =>
                                                        item.value === value,
                                                );
                                            if (option !== undefined) {
                                                navigateWithSearch(() => ({
                                                    document: undefined,
                                                    page: 1,
                                                    source: option.value,
                                                }));
                                            }
                                        }}
                                        value={sourceFilter}
                                    >
                                        <SelectTrigger
                                            aria-label="Document type filter"
                                            className="w-[180px]"
                                        >
                                            <SelectValue>
                                                {selectedSourceFilterLabel}
                                            </SelectValue>
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectGroup>
                                                {CONTENT_SOURCE_FILTER_OPTIONS.map(
                                                    (option) => (
                                                        <SelectItem
                                                            key={option.value}
                                                            value={option.value}
                                                        >
                                                            {option.label}
                                                        </SelectItem>
                                                    ),
                                                )}
                                            </SelectGroup>
                                        </SelectContent>
                                    </Select>
                                </div>
                                <TabsContent
                                    className="flex min-h-0 flex-1 flex-col gap-4"
                                    value="list"
                                >
                                    {error !== undefined && (
                                        <InlineError
                                            message={error}
                                            onRetry={() => {
                                                setRefreshCount(
                                                    (current) => current + 1,
                                                );
                                            }}
                                        />
                                    )}

                                    <DataTable
                                        columns={contentColumns}
                                        data={documents}
                                        emptyMessage="No documents matched the current filters."
                                        isLoading={loading}
                                        isRowSelected={(document) =>
                                            effectiveSelectedDocumentId ===
                                            document.id
                                        }
                                        manualPagination
                                        manualSorting
                                        onPaginationChange={onPaginationChange}
                                        onRowClick={(document) => {
                                            handleSelectDocument(document.id);
                                        }}
                                        onSortingChange={onSortingChange}
                                        pageCount={pageCount}
                                        pagination={pagination}
                                        rowCount={total}
                                        sorting={sorting}
                                        tableClassName="min-w-[760px]"
                                        wrapCellText
                                    />
                                </TabsContent>
                                <TabsContent
                                    className="min-h-0 flex-1"
                                    value="folders"
                                >
                                    <div className="flex h-full min-h-0 flex-col rounded-md border">
                                        {treeError !== undefined && (
                                            <div className="p-3">
                                                <InlineError
                                                    message={treeError}
                                                    onRetry={() => {
                                                        setRefreshCount(
                                                            (current) =>
                                                                current + 1,
                                                        );
                                                    }}
                                                />
                                            </div>
                                        )}
                                        <div className="min-h-0 flex-1 overflow-auto p-2">
                                            {treeLoading ? (
                                                <LoadingState className="min-h-40 text-sm" />
                                            ) : filteredDocumentTree.length ===
                                              0 ? (
                                                <div className="text-muted-foreground p-2 text-sm">
                                                    No documents matched the
                                                    current filters.
                                                </div>
                                            ) : (
                                                <ContentFolderTree
                                                    documentCountsByNodeId={
                                                        documentCountsByTreeNodeId
                                                    }
                                                    nodes={filteredDocumentTree}
                                                    onNodeOpenChange={
                                                        handleTreeNodeOpenChange
                                                    }
                                                    onSelectDocument={
                                                        handleSelectDocument
                                                    }
                                                    openNodeIds={
                                                        openTreeNodeIds
                                                    }
                                                />
                                            )}
                                        </div>
                                    </div>
                                </TabsContent>
                                <TabsContent
                                    className="flex min-h-0 flex-1 flex-col gap-4"
                                    value="history"
                                >
                                    {historyError !== undefined && (
                                        <InlineError
                                            message={historyError}
                                            onRetry={() => {
                                                setRefreshCount(
                                                    (current) => current + 1,
                                                );
                                            }}
                                        />
                                    )}

                                    <DataTable
                                        canRowClick={(event) =>
                                            event.document_id !== null
                                        }
                                        columns={historyColumns}
                                        data={historyEvents}
                                        emptyMessage="No history matched the current filters."
                                        isLoading={historyLoading}
                                        isRowSelected={(event) =>
                                            selectedHistoryEventId === event.id
                                        }
                                        manualPagination
                                        manualSorting
                                        onPaginationChange={onPaginationChange}
                                        onRowClick={(event) => {
                                            if (event.document_id !== null) {
                                                handleSelectDocument(
                                                    event.document_id,
                                                    event.id,
                                                );
                                            }
                                        }}
                                        onSortingChange={onSortingChange}
                                        pageCount={pageCount}
                                        pagination={pagination}
                                        rowCount={historyTotal}
                                        sorting={sorting}
                                        tableClassName="min-w-[820px]"
                                        wrapCellText
                                    />
                                </TabsContent>
                            </Tabs>
                        </section>
                    </ResizablePanel>

                    <ResizableHandle
                        className="mx-2 aria-[orientation=horizontal]:mx-0 aria-[orientation=horizontal]:my-2"
                        withHandle
                    />

                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        defaultSize="50%"
                        id="rag-exclusions-detail-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        <ContentDetailPanel
                            detailError={detailError}
                            isDetailLoading={
                                detailLoading || isSelectedDetailPending
                            }
                            onApproveLargeDocumentRender={(documentId) => {
                                setLargeDocumentsApprovedForRender(
                                    (current) => {
                                        const next = new Set(current);
                                        next.add(documentId);
                                        return next;
                                    },
                                );
                            }}
                            onCopyUrl={(url) => {
                                void copySourceUrl(url);
                            }}
                            onExclude={(document) => {
                                void excludeDocument(document);
                            }}
                            onInclude={(document) => {
                                void includeDocument(document);
                            }}
                            savingSourceKey={savingSourceKey}
                            selectedDetail={currentSelectedDetail}
                            selectedDocumentId={effectiveSelectedDocumentId}
                            selectedSummary={selectedSummary}
                            shouldGuardRender={
                                shouldGuardSelectedDocumentRender
                            }
                        />
                    </ResizablePanel>
                </ResizablePanelGroup>
            </PageSection>
        </PageShell>
    );
};
