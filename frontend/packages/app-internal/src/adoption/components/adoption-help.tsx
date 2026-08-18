import { type JSX, useState } from "react";

import { HelpButton, HelpDialog } from "../../components/help-dialog";

export const AdoptionHelp = (): JSX.Element => {
    const [open, setOpen] = useState(false);

    return (
        <>
            <HelpButton
                iconOnly
                label="About adoption metrics"
                onClick={() => {
                    setOpen(true);
                }}
            />
            <HelpDialog
                onOpenChange={setOpen}
                open={open}
                title="Understanding adoption metrics"
            >
                <div className="space-y-4 text-sm leading-relaxed">
                    <p>
                        The Adoption page shows how many people use Chat. Each
                        person is counted once on a day when they send one or
                        more messages. More messages and more chats on the same day
                        don&apos;t increase the count.
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
                            and including each date in the chart. For each new
                            chart date, the dashboard moves the period forward
                            by one day instead of using a calendar month.
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
                        <ul className="mt-1 list-inside list-disc space-y-1">
                            <li>
                                Dates use the time zone set in your browser.
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
