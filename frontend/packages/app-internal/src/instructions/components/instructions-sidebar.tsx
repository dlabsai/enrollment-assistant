import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@va/shared/components/ui/collapsible";
import { cn } from "@va/shared/lib/utils";
import { ChevronRight } from "lucide-react";
import type { JSX } from "react";

import {
    useInstructionsActions,
    useInstructionsStore,
} from "../contexts/instructions-store-context";
import {
    type AdminSection,
    buildSections,
    getTemplateLabel,
} from "../lib/sections";
import { InstructionIcon } from "./instruction-icon";

interface SectionHeaderProps {
    section: AdminSection;
    isActive: boolean;
    isExpanded: boolean;
    onSelect: () => void;
}

const SectionHeader = ({
    section,
    isActive,
    isExpanded,
    onSelect,
}: SectionHeaderProps): JSX.Element => (
    <CollapsibleTrigger
        render={
            <button
                className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                    "hover:bg-accent/50",
                    isActive
                        ? "bg-accent text-accent-foreground"
                        : "text-foreground",
                )}
                onClick={onSelect}
                type="button"
            >
                <ChevronRight
                    className={cn(
                        "size-4 shrink-0 transition-transform",
                        isExpanded ? "rotate-90" : "rotate-0",
                    )}
                />
                <span className="truncate font-medium">{section.label}</span>
            </button>
        }
    />
);

interface TemplateItemProps {
    filename: string;
}

const TemplateItem = ({ filename }: TemplateItemProps): JSX.Element => {
    const selectedTemplate = useInstructionsStore(
        (state) => state.selectedTemplate,
    );
    const drafts = useInstructionsStore((state) => state.drafts);

    const { selectTemplate } = useInstructionsActions();

    const isSelected = selectedTemplate === filename;
    const isModified = filename in drafts;

    return (
        <button
            className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                "hover:bg-accent hover:text-accent-foreground",
                isSelected ? "bg-accent text-accent-foreground" : "",
            )}
            onClick={() => {
                selectTemplate(filename);
            }}
            type="button"
        >
            <InstructionIcon filename={filename} />
            <span className="truncate">{getTemplateLabel(filename)}</span>
            {isModified && <span className="text-status-modified">*</span>}
        </button>
    );
};

interface TemplatesGroupProps {
    section: AdminSection;
}

const TemplatesGroup = ({ section }: TemplatesGroupProps): JSX.Element => (
    <div className="space-y-1">
        {section.templates.map((filename) => (
            <TemplateItem
                filename={filename}
                key={filename}
            />
        ))}
    </div>
);

export const InstructionsSidebar = (): JSX.Element => {
    const diskTemplates = useInstructionsStore((state) => state.diskTemplates);
    const activeSectionId = useInstructionsStore(
        (state) => state.activeSectionId,
    );
    const expandedSections = useInstructionsStore(
        (state) => state.expandedSections,
    );
    const { setActiveSection, setSectionExpanded } = useInstructionsActions();

    const sections = buildSections(diskTemplates);

    return (
        <aside className="bg-sidebar text-sidebar-foreground flex h-full min-h-0 w-full shrink-0 flex-col overflow-hidden border-r md:w-64">
            <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-2 py-2">
                <div className="space-y-3">
                    {sections.map((section) => {
                        const isActive = activeSectionId === section.id;
                        const isExpanded =
                            expandedSections[section.id] ?? isActive;

                        return (
                            <Collapsible
                                className="space-y-2"
                                key={section.id}
                                onOpenChange={(open) => {
                                    setSectionExpanded(section.id, open);
                                }}
                                open={isExpanded}
                            >
                                <SectionHeader
                                    isActive={isActive}
                                    isExpanded={isExpanded}
                                    onSelect={() => {
                                        setActiveSection(
                                            section.id,
                                            section.platform,
                                        );
                                    }}
                                    section={section}
                                />
                                <CollapsibleContent className="pl-6">
                                    <TemplatesGroup section={section} />
                                </CollapsibleContent>
                            </Collapsible>
                        );
                    })}
                </div>
            </div>
        </aside>
    );
};
