import { useNavigate, useSearch } from "@tanstack/react-router";
import { Button } from "@va/shared/components/ui/button";
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
import { RefreshCw } from "lucide-react";
import {
    type JSX,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError, LoadingState, PageError } from "../../components/page-state";
import {
    fetchRagChunks,
    fetchRagDocument,
    fetchRagDocumentFileExtensions,
    fetchRagDocuments,
    fetchRagDocumentTree,
    searchRagDocumentChunksBySimilarity,
} from "../lib/api";
import type { RagViewerExclusionFilter } from "../lib/search-state";
import {
    EXCLUSION_FILTER_OPTIONS,
    EXPAND_ALL_CHUNKS_STORAGE_KEY,
    getChunkSortBy,
    getSourceTypesForFilter,
    getStoredBooleanPreference,
    getStoredMarkdownViewMode,
    LARGE_MARKDOWN_RENDER_CHARACTER_THRESHOLD,
    MARKDOWN_VIEW_MODE_STORAGE_KEY,
    type MarkdownViewMode,
    type RagViewerLeftTab,
    SHOW_CHUNKS_PANE_STORAGE_KEY,
    SOURCE_FILTER_OPTIONS,
} from "../lib/viewer-utils";
import type {
    RagChunkListItem,
    RagDocumentDetailData,
    RagDocumentSimilarityMatch,
    RagDocumentSummary,
    RagDocumentTreeNode,
} from "../types";
import { RagChunkDetail } from "./rag-chunk-detail";
import { RagChunksTab } from "./rag-chunks-tab";
import { RagDocumentDetail } from "./rag-document-detail";
import { RagDocumentTree } from "./rag-document-tree";
import { RagSearchTab } from "./rag-search-tab";

export const RagViewerPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const searchState = useSearch({ from: "/rag-viewer" });
    const navigate = useNavigate({ from: "/rag-viewer" });

    const [leftTab, setLeftTab] = useState<RagViewerLeftTab>("search");
    const [documents, setDocuments] = useState<RagDocumentSummary[]>([]);
    const [similarityMatches, setSimilarityMatches] = useState<
        RagDocumentSimilarityMatch[]
    >([]);
    const [documentTree, setDocumentTree] = useState<RagDocumentTreeNode[]>([]);
    const [chunks, setChunks] = useState<RagChunkListItem[]>([]);
    const [chunksTotal, setChunksTotal] = useState(0);
    const [chunksLoading, setChunksLoading] = useState(false);
    const [chunksError, setChunksError] = useState<string | undefined>();
    const [selectedChunkId, setSelectedChunkId] = useState<
        string | undefined
    >();
    const [showChunkDocumentContext, setShowChunkDocumentContext] =
        useState(false);
    const [treeLoading, setTreeLoading] = useState(false);
    const [treeLoadedForExclusion, setTreeLoadedForExclusion] = useState<
        RagViewerExclusionFilter | undefined
    >();
    const [treeError, setTreeError] = useState<string | undefined>();
    const [openTreeNodeIds, setOpenTreeNodeIds] = useState<Set<string>>(
        () => new Set(),
    );
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [hasLoaded, setHasLoaded] = useState(false);
    const [error, setError] = useState<string | undefined>();

    const [refreshCount, setRefreshCount] = useState(0);

    const [documentDetails, setDocumentDetails] = useState<
        Record<string, RagDocumentDetailData | undefined>
    >({});
    const [expandedChunkIdsByDocument, setExpandedChunkIdsByDocument] =
        useState<Record<string, Set<string> | undefined>>({});
    const [detailLoadingId, setDetailLoadingId] = useState<
        string | undefined
    >();
    const [detailErrorsByDocumentId, setDetailErrorsByDocumentId] = useState<
        Record<string, string | undefined>
    >({});
    const [documentFileExtensions, setDocumentFileExtensions] = useState<
        string[]
    >([]);
    const [markdownViewMode, setMarkdownViewMode] = useState<MarkdownViewMode>(
        getStoredMarkdownViewMode,
    );
    const [showChunksPane, setShowChunksPane] = useState(() =>
        getStoredBooleanPreference(SHOW_CHUNKS_PANE_STORAGE_KEY, true),
    );
    const [expandAllChunks, setExpandAllChunks] = useState(() =>
        getStoredBooleanPreference(EXPAND_ALL_CHUNKS_STORAGE_KEY, false),
    );
    const [
        largeDocumentsApprovedForRender,
        setLargeDocumentsApprovedForRender,
    ] = useState<Set<string>>(() => new Set());
    const searchDebounceTimeoutRef = useRef<number | undefined>(undefined);

    const {
        document: selectedDocumentId,
        query,
        fileExtension,
        searchMode,
        source: sourceFilter,
        exclusion: exclusionFilter,
        sortBy,
        desc: descending,
        page: currentPage,
        pageSize,
    } = searchState;
    const [queryInputState, setQueryInputState] = useState(() => ({
        syncedQuery: query,
        value: query,
    }));
    const queryInput =
        queryInputState.syncedQuery === query ? queryInputState.value : query;
    const offset = (currentPage - 1) * pageSize;
    const totalPages = total === 0 ? 1 : Math.ceil(total / pageSize);
    const chunksTotalPages =
        chunksTotal === 0 ? 1 : Math.ceil(chunksTotal / pageSize);
    const selectedSourceFilterLabel =
        SOURCE_FILTER_OPTIONS.find((option) => option.value === sourceFilter)
            ?.label ?? sourceFilter;
    const selectedExclusionFilterLabel =
        EXCLUSION_FILTER_OPTIONS.find(
            (option) => option.value === exclusionFilter,
        )?.label ?? exclusionFilter;
    const chunkSortBy = getChunkSortBy(sortBy);
    const isFullTextMode = searchMode === "full_text";
    const isSimilarityMode = searchMode === "similarity";
    const isRelevanceRankedMode = isFullTextMode || isSimilarityMode;

    const navigateWithSearch = useCallback(
        (
            updater: (
                previous: typeof searchState,
            ) => Partial<typeof searchState>,
            options?: { replace?: boolean },
        ): void => {
            void navigate({
                replace: options?.replace,
                search: (previous) => ({
                    ...previous,
                    ...updater(previous),
                }),
                to: "/rag-viewer",
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

        const loadDocumentFileExtensions = async (): Promise<void> => {
            try {
                const response = await fetchRagDocumentFileExtensions(api);
                if (isActive) {
                    setDocumentFileExtensions(response.extensions);
                }
            } catch (error_) {
                if (isActive) {
                    setDocumentFileExtensions([]);
                    toast.error(
                        handleFetchError(error_, "Loading KB file extensions"),
                    );
                }
            }
        };

        void loadDocumentFileExtensions();

        return (): void => {
            isActive = false;
        };
    }, [api, refreshCount]);

    useEffect(() => {
        let isActive = true;

        const loadDocumentTree = async (): Promise<void> => {
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
                setOpenTreeNodeIds(new Set(response.map((node) => node.id)));
                setTreeLoadedForExclusion(exclusionFilter);
            } catch (error_) {
                if (!isActive) {
                    return;
                }
                setTreeError(
                    handleFetchError(error_, "Loading KB document tree"),
                );
                setDocumentTree([]);
            } finally {
                if (isActive) {
                    setTreeLoading(false);
                }
            }
        };

        if (leftTab === "tree" && treeLoadedForExclusion !== exclusionFilter) {
            void loadDocumentTree();
        }

        return (): void => {
            isActive = false;
        };
    }, [api, exclusionFilter, leftTab, refreshCount, treeLoadedForExclusion]);

    useEffect(() => {
        let isActive = true;

        const loadDocuments = async (): Promise<void> => {
            setLoading(true);
            setError(undefined);

            try {
                if (isSimilarityMode) {
                    const response =
                        query.trim() === ""
                            ? { items: [], total: 0 }
                            : await searchRagDocumentChunksBySimilarity(api, {
                                  limit: pageSize,
                                  query,
                                  fileExtension,
                                  exclusion: exclusionFilter,
                                  types: getSourceTypesForFilter(sourceFilter),
                              });
                    if (!isActive) {
                        return;
                    }
                    setSimilarityMatches(response.items);
                    setDocuments([]);
                    setTotal(response.total);
                } else {
                    const response =
                        isFullTextMode && query.trim() === ""
                            ? { items: [], total: 0 }
                            : await fetchRagDocuments(api, {
                                  limit: pageSize,
                                  offset,
                                  search: query,
                                  searchMode: isFullTextMode
                                      ? "full_text"
                                      : "exact",
                                  sortBy,
                                  descending,
                                  fileExtension,
                                  exclusion: exclusionFilter,
                                  types: getSourceTypesForFilter(sourceFilter),
                              });
                    if (!isActive) {
                        return;
                    }
                    setDocuments(response.items);
                    setSimilarityMatches([]);
                    setTotal(response.total);
                }
            } catch (error_) {
                if (!isActive) {
                    return;
                }
                setError(handleFetchError(error_, "Loading KB documents"));
                setDocuments([]);
                setSimilarityMatches([]);
                setTotal(0);
            } finally {
                if (isActive) {
                    setLoading(false);
                    setHasLoaded(true);
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
        currentPage,
        offset,
        pageSize,
        refreshCount,
        fileExtension,
        exclusionFilter,
        query,
        sortBy,
        sourceFilter,
        isSimilarityMode,
        isFullTextMode,
    ]);

    useEffect(() => {
        let isActive = true;

        const loadChunks = async (): Promise<void> => {
            setChunksLoading(true);
            setChunksError(undefined);

            try {
                const response = await fetchRagChunks(api, {
                    limit: pageSize,
                    offset,
                    search: query,
                    sortBy: chunkSortBy,
                    descending,
                    fileExtension,
                    exclusion: exclusionFilter,
                    types: getSourceTypesForFilter(sourceFilter),
                });
                if (!isActive) {
                    return;
                }
                setChunks(response.items);
                setChunksTotal(response.total);
            } catch (error_) {
                if (!isActive) {
                    return;
                }
                setChunksError(handleFetchError(error_, "Loading KB chunks"));
                setChunks([]);
                setChunksTotal(0);
            } finally {
                if (isActive) {
                    setChunksLoading(false);
                }
            }
        };

        if (leftTab === "chunks") {
            void loadChunks();
        }

        return (): void => {
            isActive = false;
        };
    }, [
        api,
        chunkSortBy,
        currentPage,
        descending,
        exclusionFilter,
        fileExtension,
        leftTab,
        offset,
        pageSize,
        query,
        refreshCount,
        sourceFilter,
    ]);

    useEffect(() => {
        if (loading) {
            return;
        }

        if (currentPage > totalPages) {
            navigateWithSearch(
                () => ({
                    document: undefined,
                    page: totalPages,
                }),
                { replace: true },
            );
        }
    }, [currentPage, loading, navigateWithSearch, total, totalPages]);

    useEffect(() => {
        if (leftTab !== "chunks" || chunksLoading) {
            return;
        }

        if (currentPage > chunksTotalPages) {
            navigateWithSearch(
                () => ({
                    document: undefined,
                    page: chunksTotalPages,
                }),
                { replace: true },
            );
        }
    }, [
        chunksLoading,
        chunksTotalPages,
        currentPage,
        leftTab,
        navigateWithSearch,
    ]);

    useEffect(() => {
        if (
            leftTab !== "search" ||
            loading ||
            selectedDocumentId === undefined
        ) {
            return;
        }

        const visibleDocumentIds = isSimilarityMode
            ? similarityMatches.map((item) => item.id)
            : documents.map((item) => item.id);

        if (!visibleDocumentIds.includes(selectedDocumentId)) {
            navigateWithSearch(
                () => ({
                    document: undefined,
                }),
                { replace: true },
            );
        }
    }, [
        documents,
        isSimilarityMode,
        leftTab,
        loading,
        navigateWithSearch,
        selectedDocumentId,
        similarityMatches,
    ]);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }

        window.localStorage.setItem(
            SHOW_CHUNKS_PANE_STORAGE_KEY,
            String(showChunksPane),
        );
    }, [showChunksPane]);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }

        window.localStorage.setItem(
            EXPAND_ALL_CHUNKS_STORAGE_KEY,
            String(expandAllChunks),
        );
    }, [expandAllChunks]);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }

        window.localStorage.setItem(
            MARKDOWN_VIEW_MODE_STORAGE_KEY,
            markdownViewMode,
        );
    }, [markdownViewMode]);

    const loadDocumentDetail = useCallback(
        async (documentId: string, force = false): Promise<void> => {
            if (!force && documentDetails[documentId] !== undefined) {
                return;
            }

            setDetailLoadingId(documentId);
            setDetailErrorsByDocumentId((current) => ({
                ...current,
                [documentId]: undefined,
            }));

            try {
                const detail = await fetchRagDocument(api, documentId);
                setDocumentDetails((current) => ({
                    ...current,
                    [documentId]: detail,
                }));
                setDetailErrorsByDocumentId((current) => ({
                    ...current,
                    [documentId]: undefined,
                }));
            } catch (error_) {
                setDetailErrorsByDocumentId((current) => ({
                    ...current,
                    [documentId]: handleFetchError(
                        error_,
                        "Loading KB document details",
                    ),
                }));
            } finally {
                setDetailLoadingId((current) =>
                    current === documentId ? undefined : current,
                );
            }
        },
        [api, documentDetails],
    );

    const handleCopyUrl = async (url: string): Promise<void> => {
        if (
            typeof window === "undefined" ||
            navigator.clipboard === undefined ||
            typeof navigator.clipboard.writeText !== "function"
        ) {
            toast.error("Clipboard is unavailable");
            return;
        }

        try {
            await navigator.clipboard.writeText(url);
            toast.success("Copied URL");
        } catch {
            toast.error("Failed to copy URL");
        }
    };

    const selectedDetail =
        selectedDocumentId === undefined
            ? undefined
            : documentDetails[selectedDocumentId];
    const selectedDetailError =
        selectedDocumentId === undefined
            ? undefined
            : detailErrorsByDocumentId[selectedDocumentId];
    const selectedChunk =
        chunks.find((chunk) => chunk.id === selectedChunkId) ?? chunks[0];
    const selectedChunkDocumentDetail =
        selectedChunk === undefined
            ? undefined
            : documentDetails[selectedChunk.document.id];
    const isSelectedChunkDocumentLoading =
        selectedChunk !== undefined &&
        detailLoadingId === selectedChunk.document.id;

    useEffect(() => {
        if (selectedDocumentId === undefined) {
            return;
        }
        void loadDocumentDetail(selectedDocumentId);
    }, [loadDocumentDetail, selectedDocumentId]);

    useEffect(() => {
        if (
            leftTab !== "chunks" ||
            !showChunkDocumentContext ||
            selectedChunk === undefined
        ) {
            return;
        }
        void loadDocumentDetail(selectedChunk.document.id);
    }, [leftTab, loadDocumentDetail, selectedChunk, showChunkDocumentContext]);

    const expandedChunkIds =
        selectedDocumentId === undefined
            ? new Set<string>()
            : (expandedChunkIdsByDocument[selectedDocumentId] ??
              new Set<string>());

    const selectedSummary = useMemo(
        () =>
            selectedDocumentId === undefined
                ? undefined
                : isSimilarityMode
                  ? similarityMatches.find(
                        (item) => item.id === selectedDocumentId,
                    )
                  : documents.find((item) => item.id === selectedDocumentId),
        [documents, isSimilarityMode, selectedDocumentId, similarityMatches],
    );
    const isSelectedDocumentLargeForRendering =
        selectedDetail !== undefined &&
        selectedDetail.character_count >
            LARGE_MARKDOWN_RENDER_CHARACTER_THRESHOLD;
    const canRenderSelectedLargeDocument =
        selectedDocumentId !== undefined &&
        largeDocumentsApprovedForRender.has(selectedDocumentId);
    const shouldGuardSelectedDocumentRender =
        markdownViewMode === "rendered" &&
        isSelectedDocumentLargeForRendering &&
        !canRenderSelectedLargeDocument;

    const handleAllChunksExpandedChange = useCallback(
        (checked: boolean): void => {
            setExpandAllChunks(checked);

            if (selectedDocumentId === undefined) {
                return;
            }

            setExpandedChunkIdsByDocument((current) => ({
                ...current,
                [selectedDocumentId]:
                    checked || selectedDetail === undefined
                        ? current[selectedDocumentId]
                        : new Set(),
            }));
        },
        [selectedDocumentId, selectedDetail],
    );

    const handleChunkOpenChange = useCallback(
        (chunkId: string, open: boolean): void => {
            if (selectedDocumentId === undefined) {
                return;
            }

            setExpandedChunkIdsByDocument((current) => {
                const next = new Set(current[selectedDocumentId]);
                if (open) {
                    next.add(chunkId);
                } else {
                    next.delete(chunkId);
                }

                return {
                    ...current,
                    [selectedDocumentId]: next,
                };
            });
        },
        [selectedDocumentId],
    );

    const handleApproveLargeDocumentRender = useCallback((): void => {
        if (selectedDocumentId === undefined) {
            return;
        }

        setLargeDocumentsApprovedForRender((current) => {
            const next = new Set(current);
            next.add(selectedDocumentId);
            return next;
        });
    }, [selectedDocumentId]);

    if (error !== undefined && !hasLoaded) {
        return (
            <PageError
                message={error}
                onRetry={() => {
                    setTreeLoadedForExclusion(undefined);
                    setRefreshCount((current) => current + 1);
                }}
            />
        );
    }

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="KB Viewer">
                <PageHeaderGroup>
                        <Select
                            onValueChange={(value) => {
                                const option = EXCLUSION_FILTER_OPTIONS.find(
                                    (item) => item.value === value,
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
                                aria-label="Status"
                                className="w-[150px]"
                            >
                                <SelectValue placeholder="Status">
                                    {selectedExclusionFilterLabel}
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    {EXCLUSION_FILTER_OPTIONS.map((option) => (
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
                </PageHeaderGroup>
                <Button
                    onClick={() => {
                        setTreeLoadedForExclusion(undefined);
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
                    id="rag-viewer-main-layout"
                    orientation="horizontal"
                    style={{ overflow: "visible" }}
                >
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        defaultSize="50%"
                        id="rag-viewer-left-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        <section className="flex h-full min-h-0 min-w-0 flex-col">
                            <Tabs
                                className="min-h-0 flex-1 gap-4"
                                onValueChange={(value: string) => {
                                    if (
                                        value === "search" ||
                                        value === "chunks" ||
                                        value === "tree"
                                    ) {
                                        setLeftTab(value);
                                    }
                                }}
                                value={leftTab}
                            >
                                <TabsList>
                                    <TabsTrigger value="search">
                                        Search
                                    </TabsTrigger>
                                    <TabsTrigger value="chunks">
                                        Chunks
                                    </TabsTrigger>
                                    <TabsTrigger value="tree">Tree</TabsTrigger>
                                </TabsList>
                                <TabsContent
                                    className="flex min-h-0 flex-1 flex-col gap-4"
                                    value="search"
                                >
                                    <RagSearchTab
                                        descending={descending}
                                        documentFileExtensions={
                                            documentFileExtensions
                                        }
                                        documents={documents}
                                        error={error}
                                        fileExtension={fileExtension}
                                        hasLoaded={hasLoaded}
                                        isFullTextMode={isFullTextMode}
                                        isRelevanceRankedMode={
                                            isRelevanceRankedMode
                                        }
                                        isSimilarityMode={isSimilarityMode}
                                        loading={loading}
                                        navigateWithSearch={navigateWithSearch}
                                        offset={offset}
                                        pageSize={pageSize}
                                        query={query}
                                        queryInput={queryInput}
                                        searchDebounceTimeoutRef={
                                            searchDebounceTimeoutRef
                                        }
                                        searchMode={searchMode}
                                        selectedDocumentId={selectedDocumentId}
                                        selectedSourceFilterLabel={
                                            selectedSourceFilterLabel
                                        }
                                        setQueryInputState={setQueryInputState}
                                        setRefreshCount={setRefreshCount}
                                        similarityMatches={similarityMatches}
                                        sortBy={sortBy}
                                        sourceFilter={sourceFilter}
                                        total={total}
                                    />
                                </TabsContent>
                                <TabsContent
                                    className="flex min-h-0 flex-1 flex-col gap-4"
                                    value="chunks"
                                >
                                    <RagChunksTab
                                        chunks={chunks}
                                        descending={descending}
                                        documentFileExtensions={
                                            documentFileExtensions
                                        }
                                        error={chunksError}
                                        fileExtension={fileExtension}
                                        loading={chunksLoading}
                                        navigateWithSearch={navigateWithSearch}
                                        offset={offset}
                                        onSelectChunk={setSelectedChunkId}
                                        pageSize={pageSize}
                                        query={query}
                                        queryInput={queryInput}
                                        searchDebounceTimeoutRef={
                                            searchDebounceTimeoutRef
                                        }
                                        selectedChunkId={selectedChunk?.id}
                                        selectedSourceFilterLabel={
                                            selectedSourceFilterLabel
                                        }
                                        setQueryInputState={setQueryInputState}
                                        setRefreshCount={setRefreshCount}
                                        sortBy={chunkSortBy}
                                        sourceFilter={sourceFilter}
                                        total={chunksTotal}
                                    />
                                </TabsContent>
                                <TabsContent
                                    className="min-h-0 flex-1"
                                    value="tree"
                                >
                                    <div className="flex h-full min-h-0 flex-col rounded-md border">
                                        {treeError !== undefined && (
                                            <div className="p-3">
                                                <InlineError
                                                    message={treeError}
                                                    onRetry={() => {
                                                        setTreeLoadedForExclusion(
                                                            undefined,
                                                        );
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
                                            ) : documentTree.length === 0 ? (
                                                <div className="text-muted-foreground p-2 text-sm">
                                                    No documents available.
                                                </div>
                                            ) : (
                                                <RagDocumentTree
                                                    nodes={documentTree}
                                                    onNodeOpenChange={(
                                                        nodeId,
                                                        open,
                                                    ) => {
                                                        setOpenTreeNodeIds(
                                                            (current) => {
                                                                const next =
                                                                    new Set(
                                                                        current,
                                                                    );
                                                                if (open) {
                                                                    next.add(
                                                                        nodeId,
                                                                    );
                                                                } else {
                                                                    next.delete(
                                                                        nodeId,
                                                                    );
                                                                }
                                                                return next;
                                                            },
                                                        );
                                                    }}
                                                    onSelectDocument={(
                                                        documentId,
                                                    ) => {
                                                        navigateWithSearch(
                                                            () => ({
                                                                document:
                                                                    documentId,
                                                            }),
                                                        );
                                                    }}
                                                    openNodeIds={
                                                        openTreeNodeIds
                                                    }
                                                    selectedDocumentId={
                                                        selectedDocumentId
                                                    }
                                                />
                                            )}
                                        </div>
                                    </div>
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
                        id="rag-viewer-right-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        {leftTab === "chunks" ? (
                            <RagChunkDetail
                                documentChunks={
                                    selectedChunkDocumentDetail?.chunks ?? []
                                }
                                isDocumentChunksLoading={
                                    isSelectedChunkDocumentLoading
                                }
                                selectedChunk={selectedChunk}
                                setShowDocumentChunks={
                                    setShowChunkDocumentContext
                                }
                                showDocumentChunks={showChunkDocumentContext}
                            />
                        ) : (
                            <RagDocumentDetail
                                detailError={selectedDetailError}
                                expandAllChunks={expandAllChunks}
                                expandedChunkIds={expandedChunkIds}
                                handleAllChunksExpandedChange={
                                    handleAllChunksExpandedChange
                                }
                                handleCopyUrl={(url) => {
                                    void handleCopyUrl(url);
                                }}
                                loadDocumentDetail={loadDocumentDetail}
                                markdownViewMode={markdownViewMode}
                                onApproveLargeDocumentRender={
                                    handleApproveLargeDocumentRender
                                }
                                onChunkOpenChange={handleChunkOpenChange}
                                selectedDetail={selectedDetail}
                                selectedDocumentId={selectedDocumentId}
                                selectedSummary={selectedSummary}
                                setMarkdownViewMode={setMarkdownViewMode}
                                setShowChunksPane={setShowChunksPane}
                                shouldGuardSelectedDocumentRender={
                                    shouldGuardSelectedDocumentRender
                                }
                                showChunksPane={showChunksPane}
                            />
                        )}
                    </ResizablePanel>
                </ResizablePanelGroup>
            </PageSection>
        </PageShell>
    );
};
