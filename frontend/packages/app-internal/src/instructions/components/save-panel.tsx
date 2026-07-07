import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogTrigger,
} from "@va/shared/components/ui/dialog";
import { Input } from "@va/shared/components/ui/input";
import { Label } from "@va/shared/components/ui/label";
import { ScrollArea } from "@va/shared/components/ui/scroll-area";
import { Separator } from "@va/shared/components/ui/separator";
import { Textarea } from "@va/shared/components/ui/textarea";
import { FileText } from "lucide-react";
import { type JSX, useState } from "react";

import {
    useInstructionsActions,
    useInstructionsStore,
} from "../contexts/instructions-store-context";
import { selectHasUnsavedChanges } from "../lib/store";
import { formatInstructionName } from "../lib/utils";

interface SavePanelContentProps {
    forceShow: boolean;
}

const SavePanelContent = ({
    forceShow,
}: SavePanelContentProps): JSX.Element => {
    const drafts = useInstructionsStore((state) => state.drafts);
    const versionName = useInstructionsStore((state) => state.versionName);
    const versionDescription = useInstructionsStore(
        (state) => state.versionDescription,
    );
    const isCreating = useInstructionsStore((state) => state.isCreating);

    const { setVersionName, setVersionDescription, createVersion } =
        useInstructionsActions();

    const displayDrafts =
        forceShow && Object.keys(drafts).length === 0
            ? { "chatbot_agent_internal.j2": "" }
            : drafts;

    return (
        <div className="bg-background">
            <div className="border-border border-b px-3">
                <div className="flex h-12 items-center">
                    <div className="text-base font-medium">Save changes</div>
                </div>
            </div>
            <div className="space-y-4 p-3">
                <p className="text-muted-foreground text-sm">
                    Create a testable version before deploying.
                </p>
                <div className="space-y-2">
                    <Label htmlFor="version-name">
                        Version name <span className="text-destructive">*</span>
                    </Label>
                    <Input
                        id="version-name"
                        onChange={(event) => {
                            setVersionName(event.target.value);
                        }}
                        placeholder="e.g., Updated guardrails"
                        value={versionName}
                    />
                </div>
                <div className="space-y-2">
                    <Label htmlFor="version-description">Description</Label>
                    <Textarea
                        id="version-description"
                        onChange={(event) => {
                            setVersionDescription(event.target.value);
                        }}
                        placeholder="Describe the changes..."
                        rows={3}
                        value={versionDescription}
                    />
                </div>
                <Separator />
                <div className="space-y-2">
                    <p className="text-sm font-medium">Modified instructions</p>
                    <ul className="text-muted-foreground space-y-1 text-sm">
                        {Object.keys(displayDrafts).map((filename) => (
                            <li
                                className="flex items-center gap-2"
                                key={filename}
                            >
                                <FileText className="size-4" />
                                {formatInstructionName(filename)}
                            </li>
                        ))}
                    </ul>
                </div>
            </div>
            <div className="border-border border-t px-3 py-3">
                <Button
                    className="w-full"
                    disabled={isCreating || !versionName.trim()}
                    onClick={() => {
                        void createVersion();
                    }}
                >
                    {isCreating ? "Creating..." : "Create version"}
                </Button>
            </div>
        </div>
    );
};

export const SaveDialog = (): JSX.Element | undefined => {
    const hasChanges = useInstructionsStore(selectHasUnsavedChanges);
    const [open, setOpen] = useState(false);

    const forceShow =
        import.meta.env.DEV &&
        window.location.search.includes("showSavePanel=1");

    if (!hasChanges && !forceShow) {
        return undefined;
    }

    return (
        <Dialog
            onOpenChange={setOpen}
            open={open}
        >
            <DialogTrigger
                render={
                    <Button
                        size="sm"
                        variant="outline"
                    >
                        Save
                    </Button>
                }
            />
            <DialogContent className="p-0 sm:max-w-xl">
                <ScrollArea className="max-h-[80vh]">
                    <SavePanelContent forceShow={forceShow} />
                </ScrollArea>
            </DialogContent>
        </Dialog>
    );
};
