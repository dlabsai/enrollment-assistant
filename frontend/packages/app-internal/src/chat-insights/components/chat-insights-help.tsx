import { type JSX, useState } from "react";

import { HelpButton, HelpDialog } from "../../components/help-dialog";

export const ChatInsightsHelp = (): JSX.Element => {
    const [open, setOpen] = useState(false);

    return (
        <>
            <HelpButton
                iconOnly
                label="About Chat Topics & Sources"
                onClick={() => {
                    setOpen(true);
                }}
            />
            <HelpDialog
                onOpenChange={setOpen}
                open={open}
                title="Understanding Chat Topics & Sources"
            >
                <div className="flex flex-col gap-4 text-sm leading-relaxed">
                    <p>
                        This page shows what staff ask about and which documents
                        the assistant uses to support its answers. The date
                        filter applies to every number, table, and trend on the
                        page.
                    </p>
                    <div>
                        <p className="text-foreground font-medium">
                            What is included
                        </p>
                        <p className="mt-1">
                            The dashboard covers regular internal staff chats.
                            Public chats, developer chats, drafts, tests, and
                            investigations are not included.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Summary numbers
                        </p>
                        <ul className="mt-1 flex list-inside list-disc flex-col gap-1">
                            <li>
                                <strong>Analyzed chats</strong> is the number of
                                chats created in the selected range that were
                                assigned topics.
                            </li>
                            <li>
                                <strong>Answers using documents</strong> is the
                                number of assistant replies backed by at least
                                one document.
                            </li>
                            <li>
                                <strong>Current documents used</strong> is the
                                number of different documents used in those
                                answers that are still available to the
                                assistant today. A document reused by many
                                answers is counted once.
                            </li>
                        </ul>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">Topics</p>
                        <ul className="mt-1 flex list-inside list-disc flex-col gap-1">
                            <li>
                                <strong>Chats with this topic</strong> counts
                                chats where a topic was either the main topic or
                                an additional topic.
                            </li>
                            <li>
                                <strong>Chats where this is primary</strong>
                                counts chats where it was the main subject.
                            </li>
                            <li>
                                <strong>Request types</strong> describe what
                                staff wanted the assistant to do, such as find
                                information or explain a next step.
                            </li>
                            <li>
                                <strong>Common combinations</strong> shows
                                topics that appeared together in the same chat.
                            </li>
                        </ul>
                        <p className="mt-2">
                            A chat can have more than one topic, so topic counts
                            can overlap and should not be added together as a
                            total.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Documents &amp; Sources
                        </p>
                        <p className="mt-1">
                            The assistant may find several possible documents,
                            but this page counts only the ones ultimately used
                            to support the answer. Other search results do not
                            count.
                        </p>
                        <ul className="mt-2 flex list-inside list-disc flex-col gap-1">
                            <li>
                                <strong>Answers</strong> is the number of
                                assistant replies that used a document.
                            </li>
                            <li>
                                <strong>Chats</strong> is the number of
                                different chats containing those replies.
                            </li>
                            <li>
                                <strong>Current KB utilization</strong> is the
                                share of documents available to the assistant
                                today that were used at least once in the date
                                range. A higher percentage does not by itself
                                mean answers were better.
                            </li>
                            <li>
                                <strong>Document subject</strong> describes
                                what a document is about. <strong>Document purpose</strong>
                                describes what kind of resource it is, such as
                                an overview or a procedure. Confidence shows how
                                certain the automated subject and purpose labels
                                were as a whole.
                            </li>
                        </ul>
                        <p className="mt-2">
                            Older documents can remain in the usage table when
                            they supported an answer during the selected range.
                            This preserves what supported past answers even
                            after a document is removed or replaced. They are
                            not included in Current documents used or Current KB
                            utilization.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">Trends</p>
                        <p className="mt-1">
                            Each cell shows how many different chats matched a
                            topic, source, or document during that period.
                            Darker cells mean more chats. Hover a cell, or focus
                            it with the keyboard, to see the exact count. The
                            periods automatically change between days, weeks,
                            and months to keep long ranges readable.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Topic definitions
                        </p>
                        <p className="mt-1">
                            Topic definitions are the rules used to decide which
                            topics apply to a chat. Built-in topics come with
                            the dashboard; custom topics were added by
                            authorized staff. When a definition changes, past
                            chats are updated before the change appears in
                            reports.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Data updates and limitations
                        </p>
                        <ul className="mt-1 flex list-inside list-disc flex-col gap-1">
                            <li>
                                <strong>Data through</strong> is the latest
                                point included in the saved analysis.
                            </li>
                            <li>
                                <strong>Refresh</strong> reloads saved results;
                                it does not perform new analysis. If available,
                                <strong> Run analysis</strong> starts an update.
                            </li>
                            <li>
                                Protected document counts follow your access,
                                so another viewer may see different totals.
                            </li>
                            <li>
                                Topics, document subjects, and document purposes
                                are generated by AI for exploration. They are
                                not audited facts or a measure of answer quality.
                            </li>
                        </ul>
                    </div>
                </div>
            </HelpDialog>
        </>
    );
};
