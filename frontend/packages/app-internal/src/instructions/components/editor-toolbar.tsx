import { Button } from "@va/shared/components/ui/button";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import {
    Sheet,
    SheetContent,
    SheetTrigger,
} from "@va/shared/components/ui/sheet";
import { useSidebar } from "@va/shared/components/ui/sidebar";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import {
    GitCompareArrows,
    Menu,
    MessageSquareText,
    PanelLeft,
    Rocket,
    Trash2,
    WrapText,
} from "lucide-react";
import { type JSX, useMemo } from "react";

import {
    useInstructionsActions,
    useInstructionsStore,
} from "../contexts/instructions-store-context";
import { isAssistantSectionId } from "../lib/sections";
import { HelpButton } from "./help-guide";
import { InstructionsSidebar } from "./instructions-sidebar";
import { SaveDialog } from "./save-panel";
import { StatusBadges } from "./status-badges";

const DEFAULT_VERSION_OPTION = "default";

export const EditorToolbar = (): JSX.Element | undefined => {
    const selectedTemplate = useInstructionsStore(
        (state) => state.selectedTemplate,
    );
    const selectedVersionDetail = useInstructionsStore(
        (state) => state.selectedVersionDetail,
    );
    const deployedVersion = useInstructionsStore(
        (state) => state.deployedVersion,
    );
    const showDiff = useInstructionsStore((state) => state.showDiff);
    const wrapLines = useInstructionsStore((state) => state.wrapLines);
    const activeSectionId = useInstructionsStore(
        (state) => state.activeSectionId,
    );
    const versionsBySection = useInstructionsStore(
        (state) => state.versionsBySection,
    );
    const versions =
        activeSectionId === undefined
            ? []
            : (versionsBySection[activeSectionId] ?? []);
    const selectedVersionId = useInstructionsStore(
        (state) => state.selectedVersionId,
    );
    const isDefaultSelected = useInstructionsStore(
        (state) => state.isDefaultSelected,
    );
    const diskTemplates = useInstructionsStore((state) => state.diskTemplates);
    const drafts = useInstructionsStore((state) => state.drafts);
    const isDeploying = useInstructionsStore((state) => state.isDeploying);
    const isDeleting = useInstructionsStore((state) => state.isDeleting);
    const isChatPanelOpen = useInstructionsStore(
        (state) => state.isChatPanelOpen,
    );

    const { toggleSidebar } = useSidebar();

    const isModified =
        selectedTemplate === undefined ? false : selectedTemplate in drafts;

    const {
        toggleDiff,
        toggleWrapLines,
        requestResetTemplate,
        requestSelectDefault,
        requestSelectVersion,
        deployVersion,
        undeployVersion,
        requestDeleteVersion,
        toggleChatPanel,
    } = useInstructionsActions();

    const selectedVersion = versions.find(
        (version) => version.id === selectedVersionId,
    );
    const selectedVersionIdValue = selectedVersion?.id;

    const versionValue =
        isDefaultSelected || selectedVersionId === undefined
            ? DEFAULT_VERSION_OPTION
            : selectedVersionId;

    const selectedVersionLabel =
        isDefaultSelected || selectedVersionId === undefined
            ? "Default"
            : selectedVersion === undefined
              ? selectedVersionDetail?.id === selectedVersionId
                  ? `v${selectedVersionDetail.version_number} – ${selectedVersionDetail.name}`
                  : undefined
              : `v${selectedVersion.version_number} – ${selectedVersion.name}`;

    const canDeploy =
        selectedVersion !== undefined && !selectedVersion.is_deployed;
    const canUndeploy = isDefaultSelected && deployedVersion?.id !== undefined;
    const canDelete =
        selectedVersion !== undefined && !selectedVersion.is_deployed;
    const loading = isDeploying || isDeleting;

    const modifiedPromptsCount = useMemo(() => {
        if (!selectedVersionDetail) {
            return 0;
        }
        return selectedVersionDetail.prompts.filter((prompt) => {
            const diskTemplate = diskTemplates.find(
                (template) => template.filename === prompt.filename,
            );
            const currentContent = drafts[prompt.filename] ?? prompt.content;
            return diskTemplate?.content !== currentContent;
        }).length;
    }, [diskTemplates, drafts, selectedVersionDetail]);

    const showVersionControls = activeSectionId !== undefined;
    const showTestChatToggle = isAssistantSectionId(activeSectionId);

    return (
        <div className="border-border border-b px-2 py-2">
            <div className="flex flex-wrap items-center gap-2">
                <Button
                    className="md:hidden"
                    onClick={toggleSidebar}
                    size="icon-sm"
                    type="button"
                    variant="outline"
                >
                    <PanelLeft />
                    <span className="sr-only">Open sidebar</span>
                </Button>
                <Sheet>
                    <SheetTrigger
                        render={
                            <Button
                                className="md:hidden"
                                size="icon-sm"
                                type="button"
                                variant="outline"
                            >
                                <Menu />
                                <span className="sr-only">Open navigation</span>
                            </Button>
                        }
                    />
                    <SheetContent
                        className="w-80! max-w-none! overflow-x-hidden p-0"
                        side="left"
                    >
                        <InstructionsSidebar />
                    </SheetContent>
                </Sheet>
                {showVersionControls && (
                    <Select
                        onValueChange={(value) => {
                            if (value === null) {
                                return;
                            }

                            if (value === DEFAULT_VERSION_OPTION) {
                                requestSelectDefault();
                            } else {
                                requestSelectVersion(value);
                            }
                        }}
                        value={versionValue}
                    >
                        <SelectTrigger className="w-48">
                            <SelectValue placeholder="Select version">
                                {selectedVersionLabel}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value={DEFAULT_VERSION_OPTION}>
                                    Default
                                </SelectItem>
                                {versions.map((version) => (
                                    <SelectItem
                                        key={version.id}
                                        value={version.id}
                                    >
                                        v{version.version_number} –{" "}
                                        {version.name}
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                )}
                {showVersionControls &&
                    canDeploy &&
                    selectedVersionIdValue !== undefined && (
                        <Button
                            disabled={loading}
                            onClick={() => {
                                void deployVersion(selectedVersionIdValue);
                            }}
                            size="sm"
                            variant="outline"
                        >
                            <Rocket data-icon="inline-start" />
                            Deploy
                        </Button>
                    )}
                {showVersionControls && canUndeploy && (
                    <Button
                        disabled={loading}
                        onClick={() => {
                            void undeployVersion();
                        }}
                        size="sm"
                        variant="outline"
                    >
                        <Rocket data-icon="inline-start" />
                        Deploy
                    </Button>
                )}
                {showVersionControls &&
                    canDelete &&
                    selectedVersionIdValue !== undefined && (
                        <Button
                            disabled={loading}
                            onClick={() => {
                                requestDeleteVersion(selectedVersionIdValue);
                            }}
                            size="sm"
                            variant="outline"
                        >
                            <Trash2 data-icon="inline-start" />
                            Delete
                        </Button>
                    )}
                {selectedTemplate !== undefined && (
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        disabled={!isModified}
                                        onClick={toggleDiff}
                                        size="icon-sm"
                                        variant={
                                            showDiff ? "secondary" : "outline"
                                        }
                                    >
                                        <GitCompareArrows />
                                    </Button>
                                }
                            />
                            <TooltipContent>
                                {showDiff ? "Hide" : "Show"} diff
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                )}
                {selectedTemplate !== undefined && (
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        onClick={toggleWrapLines}
                                        size="icon-sm"
                                        variant={
                                            wrapLines ? "secondary" : "outline"
                                        }
                                    >
                                        <WrapText />
                                    </Button>
                                }
                            />
                            <TooltipContent>
                                {wrapLines ? "Disable" : "Enable"} line wrapping
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                )}
                {selectedTemplate !== undefined && isModified && (
                    <Button
                        onClick={requestResetTemplate}
                        size="sm"
                        variant="outline"
                    >
                        Reset
                    </Button>
                )}
                <SaveDialog />
                {showTestChatToggle && (
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        onClick={toggleChatPanel}
                                        size="icon-sm"
                                        variant={
                                            isChatPanelOpen
                                                ? "secondary"
                                                : "outline"
                                        }
                                    >
                                        <MessageSquareText />
                                    </Button>
                                }
                            />
                            <TooltipContent>
                                {isChatPanelOpen ? "Hide" : "Show"} test chat
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                )}
                <div className="flex flex-wrap items-center gap-2 md:ml-auto">
                    {selectedTemplate === undefined &&
                        selectedVersionDetail !== undefined && (
                            <div className="text-muted-foreground text-sm">
                                v{selectedVersionDetail.version_number} –{" "}
                                {selectedVersionDetail.name} •{" "}
                                {modifiedPromptsCount} modified •{" "}
                                {selectedVersionDetail.created_by_name}
                            </div>
                        )}
                    <StatusBadges />
                    <HelpButton />
                </div>
            </div>
        </div>
    );
};
