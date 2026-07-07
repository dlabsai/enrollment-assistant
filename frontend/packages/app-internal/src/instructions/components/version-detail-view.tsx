import { StreamLanguage } from "@codemirror/language";
import { jinja2 } from "@codemirror/legacy-modes/mode/jinja2";
import { EditorView } from "@codemirror/view";
import { githubDark, githubLight } from "@uiw/codemirror-theme-github";
import { ScrollArea } from "@va/shared/components/ui/scroll-area";
import { type JSX, useMemo } from "react";
import CodeMirrorMerge from "react-codemirror-merge";

import { useDarkMode } from "../../lib/hooks/use-dark-mode";
import { useInstructionsStore } from "../contexts/instructions-store-context";
import { formatInstructionName } from "../lib/utils";
import { InstructionIcon } from "./instruction-icon";

const jinja2Language = StreamLanguage.define(jinja2);

interface PromptDiffCardProps {
    filename: string;
    content: string;
    originalContent: string;
    fillHeight?: boolean;
}

const PromptDiffCard = ({
    filename,
    content,
    originalContent,
    fillHeight = false,
}: PromptDiffCardProps): JSX.Element => {
    const wrapLines = useInstructionsStore((state) => state.wrapLines);
    const isDarkMode = useDarkMode();

    const editorExtensions = useMemo(
        () =>
            wrapLines
                ? [jinja2Language, EditorView.lineWrapping]
                : [jinja2Language],
        [wrapLines],
    );

    return (
        <div
            className={
                fillHeight
                    ? "border-border flex min-h-0 flex-1 flex-col rounded-lg border"
                    : "border-border rounded-lg border"
            }
        >
            <div className="bg-muted/30 border-border flex items-center gap-2 border-b px-3 py-2">
                <InstructionIcon filename={filename} />
                <span className="font-medium">
                    {formatInstructionName(filename)}
                </span>
            </div>
            <div className={fillHeight ? "min-h-0 flex-1" : "h-64"}>
                <CodeMirrorMerge
                    className="h-full [&_.cm-editor]:h-full [&_.cm-mergeView]:h-full [&_.cm-scroller]:overflow-auto"
                    collapseUnchanged={{
                        margin: 3,
                        minSize: 4,
                    }}
                    theme={isDarkMode ? githubDark : githubLight}
                >
                    <CodeMirrorMerge.Original
                        extensions={editorExtensions}
                        readOnly
                        value={originalContent}
                    />
                    <CodeMirrorMerge.Modified
                        extensions={editorExtensions}
                        readOnly
                        value={content}
                    />
                </CodeMirrorMerge>
            </div>
        </div>
    );
};

export const VersionDetailView = (): JSX.Element | undefined => {
    const selectedVersionDetail = useInstructionsStore(
        (state) => state.selectedVersionDetail,
    );
    const diskTemplates = useInstructionsStore((state) => state.diskTemplates);

    if (!selectedVersionDetail) {
        return undefined;
    }

    const modifiedPrompts = selectedVersionDetail.prompts.filter((prompt) => {
        const diskTemplate = diskTemplates.find(
            (template) => template.filename === prompt.filename,
        );
        return diskTemplate?.content !== prompt.content;
    });

    const fillHeight = modifiedPrompts.length === 1;

    return (
        <ScrollArea className="min-h-0 flex-1">
            <div
                className={
                    fillHeight
                        ? "flex h-full min-h-0 flex-col p-3"
                        : "space-y-6 p-3"
                }
            >
                {modifiedPrompts.map((prompt) => {
                    const diskTemplate = diskTemplates.find(
                        (template) => template.filename === prompt.filename,
                    );
                    return (
                        <PromptDiffCard
                            content={prompt.content}
                            filename={prompt.filename}
                            fillHeight={fillHeight}
                            key={prompt.id}
                            originalContent={diskTemplate?.content ?? ""}
                        />
                    );
                })}
            </div>
        </ScrollArea>
    );
};
