import { Badge } from "@va/shared/components/ui/badge";
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@va/shared/components/ui/collapsible";
import { cn } from "@va/shared/lib/utils";
import { FileText, Folder, FolderOpen } from "lucide-react";
import type { JSX } from "react";

import { formatNumber } from "../lib/viewer-utils";
import type { RagDocumentTreeNode } from "../types";

interface RagDocumentTreeProps {
    nodes: RagDocumentTreeNode[];
    openNodeIds: Set<string>;
    selectedDocumentId: string | undefined;
    onNodeOpenChange: (nodeId: string, open: boolean) => void;
    onSelectDocument: (documentId: string) => void;
}

export const RagDocumentTree = ({
    nodes,
    openNodeIds,
    selectedDocumentId,
    onNodeOpenChange,
    onSelectDocument,
}: RagDocumentTreeProps): JSX.Element => {
    const renderNodes = (treeNodes: RagDocumentTreeNode[], depth: number): JSX.Element[] =>
        treeNodes.map((node) => {
            const isFolder = node.children.length > 0;
            const isOpen = openNodeIds.has(node.id);
            const isSelected = node.document_id === selectedDocumentId;

            if (!isFolder) {
                return (
                    <button
                        className={cn(
                            "hover:bg-muted/70 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                            isSelected && "bg-muted ring-primary/20 ring-1",
                        )}
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
                        <span className="min-w-0 flex-1 truncate">{node.label}</span>
                        {node.excluded ? <Badge className="shrink-0" variant="secondary">Excluded</Badge> : null}
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
                        <span className="min-w-0 flex-1 truncate">{node.label}</span>
                        <Badge className="shrink-0" variant="outline">
                            {formatNumber(node.children.length)}
                        </Badge>
                    </CollapsibleTrigger>
                    <CollapsibleContent>{renderNodes(node.children, depth + 1)}</CollapsibleContent>
                </Collapsible>
            );
        });

    return <div className="flex flex-col gap-1">{renderNodes(nodes, 0)}</div>;
};
