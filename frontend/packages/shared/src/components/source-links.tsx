import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@va/shared/components/ui/collapsible";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import type { MessageSourceUsed } from "@va/shared/types";
import { ChevronDown, ExternalLink, FileText } from "lucide-react";
import { type JSX, useState } from "react";

const SOURCE_LABELS: Record<MessageSourceUsed["type"], string> = {
    website_page: "Website page",
    website_program: "Website program",
    catalog_page: "Catalog page",
    catalog_program: "Catalog program",
    catalog_course: "Catalog course",
    training_material: "Training material",
    canned_response: "Assistant instructions",
};

const TOOL_LABELS: Record<string, string> = {
    find_document_chunks: "Document search",
    find_document_titles: "Title search",
    retrieve_documents: "Document retrieval",
    list_catalog_pages: "Catalog pages lookup",
    list_catalog_programs: "Catalog programs lookup",
    list_catalog_programs_by_school: "Catalog programs by school lookup",
    list_catalog_courses: "Catalog courses lookup",
    list_catalog_courses_for_program: "Catalog courses lookup",
    canned_response: "Assistant instructions",
};

const getSourceDeduplicationKey = (source: MessageSourceUsed): string =>
    `${source.type}:${source.id}:${source.url}`;

const getSearchQuery = (source: MessageSourceUsed): string | undefined => {
    const searchQuery = source.search_query?.trim();
    return searchQuery === undefined || searchQuery === ""
        ? undefined
        : searchQuery;
};

interface SourceLinksProps {
    sources: MessageSourceUsed[] | undefined;
    emptyMessage?: string;
    grouped?: boolean;
}

interface SourceEntry {
    key: string;
    source: MessageSourceUsed;
}

const deduplicateSourceEntries = (entries: SourceEntry[]): SourceEntry[] => {
    const seen = new Set<string>();
    const deduplicated: SourceEntry[] = [];
    for (const entry of entries) {
        const deduplicationKey = getSourceDeduplicationKey(entry.source);
        if (!seen.has(deduplicationKey)) {
            seen.add(deduplicationKey);
            deduplicated.push(entry);
        }
    }
    return deduplicated;
};

interface SourceToolSection {
    key: string;
    id: string;
    toolName: string;
    searchQuery?: string;
    sources: SourceEntry[];
}

const buildToolSections = (
    sources: MessageSourceUsed[],
): SourceToolSection[] => {
    const sections: SourceToolSection[] = [];
    for (const source of sources) {
        const current = sections.at(-1);
        const searchQuery = getSearchQuery(source);
        const entry: SourceEntry = { key: source.key, source };
        if (current?.id === source.tool_call_id) {
            current.sources.push(entry);
            current.searchQuery ??= searchQuery;
        } else {
            sections.push({
                key: `${source.tool_call_id}:${sections.length}`,
                id: source.tool_call_id,
                toolName: source.tool_name,
                searchQuery,
                sources: [entry],
            });
        }
    }
    return sections;
};

interface SourceToolSectionViewProps {
    section: SourceToolSection;
}

interface SourceListProps {
    sources: SourceEntry[];
    showSnippets?: boolean;
}

const SourceList = ({
    sources,
    showSnippets = false,
}: SourceListProps): JSX.Element => (
    <div className="flex flex-col gap-2">
        {sources.map(({ key, source }) => {
            const url = source.url.trim();
            const hasUrl = url !== "";
            const explanation = source.explanation?.trim();
            const chunk = source.chunk?.trim();
            const promptSourceExplanation =
                explanation !== undefined && explanation !== ""
                    ? explanation
                    : chunk;
            return (
                <div
                    className="grid min-w-0 grid-cols-[0.5rem_minmax(0,1fr)] gap-2"
                    key={key}
                >
                    <span
                        aria-hidden="true"
                        className="bg-muted-foreground/70 mt-2 size-1.5 rounded-full"
                    />
                    <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            {hasUrl ? (
                                <a
                                    className="text-primary hover:text-primary/80 inline-flex items-start gap-1 font-medium underline-offset-2 hover:underline"
                                    href={url}
                                    rel="noreferrer"
                                    target="_blank"
                                >
                                    <span>{source.title}</span>
                                    <ExternalLink className="mt-0.5 size-3 shrink-0" />
                                </a>
                            ) : (
                                <span className="text-foreground font-medium">
                                    {source.title}
                                </span>
                            )}
                            <span className="text-muted-foreground text-xs">
                                {SOURCE_LABELS[source.type]}
                            </span>
                            {!hasUrl &&
                            promptSourceExplanation !== undefined &&
                            promptSourceExplanation !== "" ? (
                                <p className="text-muted-foreground basis-full text-xs leading-relaxed">
                                    {promptSourceExplanation}
                                </p>
                            ) : undefined}
                            {showSnippets &&
                            hasUrl &&
                            source.chunk !== undefined &&
                            source.chunk !== null &&
                            source.chunk !== "" ? (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <span
                                                aria-label="Show retrieved snippet"
                                                className="text-muted-foreground hover:text-foreground inline-flex cursor-help items-center"
                                                role="button"
                                                tabIndex={0}
                                            >
                                                <FileText className="size-3" />
                                            </span>
                                        }
                                    />
                                    <TooltipContent
                                        className="max-h-80 max-w-xl overflow-auto p-3 text-left leading-relaxed whitespace-pre-wrap"
                                        side="top"
                                    >
                                        {source.chunk}
                                    </TooltipContent>
                                </Tooltip>
                            ) : undefined}
                        </div>
                    </div>
                </div>
            );
        })}
    </div>
);

const SourceToolSectionView = ({
    section,
}: SourceToolSectionViewProps): JSX.Element => {
    const [open, setOpen] = useState(section.toolName === "retrieve_documents");
    const toolLabel = TOOL_LABELS[section.toolName] ?? section.toolName;
    const sourceCountLabel = String(section.sources.length);

    return (
        <Collapsible
            onOpenChange={setOpen}
            open={open}
            render={<div />}
        >
            <CollapsibleTrigger
                render={
                    <button
                        aria-label={
                            open ? "Hide tool sources" : "Show tool sources"
                        }
                        className="flex w-full items-start gap-2 py-1 text-left"
                        type="button"
                    >
                        <ChevronDown
                            aria-hidden="true"
                            className={`text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
                        />
                        <span className="min-w-0">
                            <span className="flex items-center gap-2">
                                <span className="text-foreground text-sm font-medium">
                                    {toolLabel}
                                </span>
                                <span className="text-muted-foreground text-xs">
                                    {sourceCountLabel}
                                </span>
                            </span>
                        </span>
                    </button>
                }
            />
            <CollapsibleContent>
                <div className="flex flex-col gap-2 py-2 pl-6">
                    {section.searchQuery === undefined ? undefined : (
                        <div className="text-muted-foreground text-xs">
                            {section.searchQuery}
                        </div>
                    )}
                    <SourceList
                        showSnippets
                        sources={section.sources}
                    />
                </div>
            </CollapsibleContent>
        </Collapsible>
    );
};

export const SourceLinks = ({
    sources,
    emptyMessage,
    grouped = true,
}: SourceLinksProps): JSX.Element | undefined => {
    if (sources === undefined || sources.length === 0) {
        if (emptyMessage !== undefined && emptyMessage !== "") {
            return (
                <div className="text-muted-foreground mt-3 rounded-md border border-dashed px-3 py-2 text-sm">
                    {emptyMessage}
                </div>
            );
        }
        return undefined;
    }

    const sections = buildToolSections(sources);
    const flatSources = deduplicateSourceEntries(
        sources.map((source) => ({
            key: source.key,
            source,
        })),
    );
    return (
        <TooltipProvider delay={0}>
            <div className="mt-3 flex flex-col gap-2 text-sm">
                {grouped ? (
                    sections.map((section) => (
                        <SourceToolSectionView
                            key={section.key}
                            section={section}
                        />
                    ))
                ) : (
                    <SourceList sources={flatSources} />
                )}
            </div>
        </TooltipProvider>
    );
};
