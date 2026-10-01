import { type JSX, useState } from "react";

import { HelpButton, HelpDialog } from "../../components/help-dialog";

export const AdoptionHelp = (): JSX.Element => {
    const [open, setOpen] = useState(false);

    return (
        <>
            <HelpButton
                iconOnly
                label="About user analytics"
                onClick={() => {
                    setOpen(true);
                }}
            />
            <HelpDialog
                onOpenChange={setOpen}
                open={open}
                title="Understanding user analytics"
            >
                <div className="flex flex-col gap-4 text-sm leading-relaxed">
                    <p>
                        User Analytics shows new account creation and Chat usage
                        during the selected range.
                    </p>
                    <div>
                        <p className="text-foreground font-medium">
                            New accounts
                        </p>
                        <p className="mt-1">
                            Created shows how many accounts were added during
                            the selected range. Used Chat and Did not use Chat
                            split those new accounts based on activity during
                            the same range.
                        </p>
                    </div>
                    <p>
                        Adoption metrics show how many people use Chat. Each
                        person is counted once on a day when they send one or
                        more messages. More messages and more chats on the same
                        day don&apos;t increase the count.
                    </p>
                    <div>
                        <p className="text-foreground font-medium">
                            Daily active users
                        </p>
                        <p className="mt-1">
                            Daily active users means the number of different
                            people who sent a message on a given day. The card
                            shows the count for the last day in the selected
                            date range.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Monthly active users
                        </p>
                        <p className="mt-1">
                            Monthly active users means the number of different
                            people who sent a message during the 30 days up to
                            and including each point in the chart. Chart points
                            can represent hours, days, weeks, or months,
                            depending on the selected date range.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Average daily users
                        </p>
                        <p className="mt-1">
                            Average daily users means the average daily active
                            user count for the selected date range. Days when
                            nobody sent a message are included as zero.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            DAU / MAU stickiness
                        </p>
                        <p className="mt-1">
                            The percentage shows what share of monthly active
                            users also used Chat on the last day. For example,
                            25% means one in four monthly active users used Chat
                            on the last day.
                        </p>
                    </div>
                    <div>
                        <p className="text-foreground font-medium">
                            Filters and counting rules
                        </p>
                        <ul className="mt-1 flex list-inside list-disc flex-col gap-1">
                            <li>
                                Dates use the app time zone. It defaults to
                                browser time; developers can select Eastern Time
                                in the sidebar Settings menu.
                            </li>
                            <li>
                                The date filter sets the period shown on the
                                page. The user filter changes every card and
                                chart.
                            </li>
                        </ul>
                    </div>
                </div>
            </HelpDialog>
        </>
    );
};
