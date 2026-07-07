import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import { HelpCircle } from "lucide-react";
import type { JSX } from "react";

import {
    useInstructionsActions,
    useInstructionsStore,
} from "../contexts/instructions-store-context";

export const HelpGuide = (): JSX.Element => {
    const showGuide = useInstructionsStore((state) => state.showGuide);
    const { dismissGuide } = useInstructionsActions();

    return (
        <Dialog
            onOpenChange={(open) => {
                if (!open) {
                    dismissGuide();
                }
            }}
            open={showGuide}
        >
            <DialogContent className="flex max-h-[85vh] flex-col">
                <DialogHeader>
                    <DialogTitle>Instructions Guide</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 overflow-y-auto text-sm leading-relaxed">
                    <div>
                        <p className="text-foreground font-medium">
                            Instructions workspace
                        </p>
                        <p className="mt-1">
                            Select a section and instruction template from the
                            sidebar. Sections group assistant and helper
                            templates, and each section is versioned together.
                            This internal workspace shows internal VA
                            instructions only. An asterisk indicates unsaved
                            edits.
                        </p>
                        <ol className="mt-2 list-inside list-decimal space-y-1">
                            <li>
                                <strong className="text-foreground">
                                    Edit
                                </strong>{" "}
                                – Update the template in the editor. Use Diff,
                                Wrap, and Reset to review changes.
                            </li>
                            <li>
                                <strong className="text-foreground">
                                    Save
                                </strong>{" "}
                                – Create a version (required for testing or
                                deployment).
                            </li>
                            <li>
                                <strong className="text-foreground">
                                    Review versions
                                </strong>{" "}
                                – Use the version dropdown to switch between
                                Default and saved versions. Selecting a version
                                shows the modified prompts.
                            </li>
                            <li>
                                <strong className="text-foreground">
                                    Deploy
                                </strong>{" "}
                                – Make a version live. Revert returns to Default
                                and Delete removes unused versions.
                            </li>
                        </ol>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Test chat (assistant only)
                        </p>
                        <p className="mt-1">
                            Open the chat panel with the message icon, then
                            select a version to test. Test chat uses saved
                            versions, not unsaved edits.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Chat turn (assistant)
                        </p>
                        <p className="mt-1">
                            Each user message runs this loop in the backend.
                            Search runs per iteration, and guardrails feedback
                            is injected into the chatbot prompt until it passes
                            or retries are exhausted.
                        </p>
                        <pre className="bg-muted/40 text-muted-foreground mt-2 rounded-md p-3 text-xs leading-relaxed whitespace-pre-wrap">
                            {`User message
  -> Search (tools)
  -> Chatbot (uses search + guardrails feedback)
  -> Guardrails (validate response)
  -> if invalid: feedback -> Chatbot (repeat)
  -> if retries exhausted: response saved as guardrails-blocked`}
                        </pre>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Helper instructions (background jobs)
                        </p>
                        <p className="mt-1">
                            Helper sections run outside the main turn. They are
                            versioned separately and triggered by background
                            workflows.
                        </p>
                        <pre className="bg-muted/40 text-muted-foreground mt-2 rounded-md p-3 text-xs leading-relaxed whitespace-pre-wrap">
                            {`Internal chats
  -> Title (Internal) (initial title)
  -> Title Transcript (Internal) (title from transcript + regenerate)
  -> Summary (Internal) (internal summary after each message)`}
                        </pre>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">Settings</p>
                        <p className="mt-1">
                            Application-level overrides live in the Settings
                            page (university info, contact details, and the
                            guardrails blocked message). Leave fields empty to
                            use system defaults.
                        </p>
                    </div>
                </div>
                <DialogFooter>
                    <Button
                        onClick={dismissGuide}
                        type="button"
                        variant="outline"
                    >
                        Close
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

export const HelpButton = (): JSX.Element | undefined => {
    const { showGuidePanel } = useInstructionsActions();

    return (
        <Button
            onClick={showGuidePanel}
            size="sm"
            variant="outline"
        >
            <HelpCircle data-icon="inline-start" />
            Help
        </Button>
    );
};
