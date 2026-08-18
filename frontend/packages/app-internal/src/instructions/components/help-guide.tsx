import type { JSX } from "react";

import { HelpDialog } from "../../components/help-dialog";
import {
    useInstructionsActions,
    useInstructionsStore,
} from "../contexts/instructions-store-context";

export const HelpGuide = (): JSX.Element => {
    const showGuide = useInstructionsStore((state) => state.showGuide);
    const { dismissGuide } = useInstructionsActions();

    return (
        <HelpDialog
            onOpenChange={(open) => {
                if (!open) {
                    dismissGuide();
                }
            }}
            open={showGuide}
            title="Instructions Guide"
        >
            <div className="space-y-4 text-sm leading-relaxed">
                <div>
                    <p className="text-foreground font-medium">
                        Instructions workspace
                    </p>
                    <p className="mt-1">
                        Select a section and instructions from the sidebar.
                        Sections group assistant and helper instructions, and
                        each section is versioned together. This internal
                        workspace shows internal VA instructions only. An
                        asterisk indicates unsaved edits.
                    </p>
                    <ol className="mt-2 list-inside list-decimal space-y-1">
                        <li>
                            <strong className="text-foreground">Edit</strong> –
                            Update the selected instructions in the editor. Use
                            Show diff, Enable wrap, and Reset to review changes.
                        </li>
                        <li>
                            <strong className="text-foreground">Save</strong> –
                            Create a saved version of the instructions when you
                            are ready to keep or deploy them.
                        </li>
                        <li>
                            <strong className="text-foreground">
                                Review saved versions
                            </strong>{" "}
                            – Use the version dropdown to switch between Default
                            and a saved version of the instructions. Selecting a
                            saved version shows the modified instructions.
                        </li>
                        <li>
                            <strong className="text-foreground">Deploy</strong>{" "}
                            – Make a saved version of the instructions live.
                            Revert returns to Default and Delete removes unused
                            saved versions.
                        </li>
                    </ol>
                </div>
                <div>
                    <p className="text-foreground font-medium">
                        Test chat (Assistant only)
                    </p>
                    <p className="mt-1">
                        Use Show test chat in the toolbar. Test chat uses the
                        current Assistant instructions, including unsaved edits.
                        After editing instructions during a chat, use New chat
                        when you want a clean test of the latest instructions.
                    </p>
                </div>
                <div>
                    <p className="text-foreground font-medium">
                        Eval Runner (Assistant only)
                    </p>
                    <p className="mt-1">
                        For full-suite testing, open Eval Runner and select Live
                        instructions, the current Unsaved draft, or a saved
                        version. Unsaved draft runs use the latest unsaved
                        Assistant edits in this workspace.
                    </p>
                </div>
                <div>
                    <p className="text-foreground font-medium">
                        Assistant response flow
                    </p>
                    <p className="mt-1">
                        Each Assistant message follows this loop. Search runs
                        per iteration, then guardrails review the answer. If
                        guardrails reject it, the feedback is applied and the
                        Assistant retries until it passes or retries are
                        exhausted.
                    </p>
                    <pre className="bg-muted/40 text-muted-foreground mt-2 rounded-md p-3 text-xs leading-relaxed whitespace-pre-wrap">
                        {`User message
  -> Search relevant sources
  -> Assistant drafts an answer
  -> Guardrails review the answer
  -> if rejected: apply feedback and retry
  -> if retries exhausted: show the blocked-response message`}
                    </pre>
                </div>
                <div>
                    <p className="text-foreground font-medium">
                        Helper instructions (supporting workflows)
                    </p>
                    <p className="mt-1">
                        Helper sections are versioned separately and used by
                        supporting workflows such as titles and summaries.
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
                        Application-level overrides live in the Settings page
                        (university info, contact details, and the guardrails
                        blocked message). Leave fields empty to use system
                        defaults.
                    </p>
                </div>
            </div>
        </HelpDialog>
    );
};
