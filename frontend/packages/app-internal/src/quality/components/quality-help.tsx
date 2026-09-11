import type { JSX } from "react";

import { HelpDialog } from "../../components/help-dialog";

interface QualityHelpProps {
    onOpenChange: (open: boolean) => void;
    open: boolean;
}

export const QualityHelp = ({
    onOpenChange,
    open,
}: QualityHelpProps): JSX.Element => (
    <HelpDialog
        onOpenChange={onOpenChange}
        open={open}
        title="Quality metrics"
    >
        <div className="flex flex-col gap-3 text-sm">
            <p>
                The filters at the top set the platform, people, and time range
                for the entire dashboard.
            </p>
            <p>
                Responsiveness measures backend processing time until an
                assistant response is ready; it does not measure satisfaction.
                The median is the midpoint, while P95 is the time within which
                95% of measured responses were ready.
            </p>
            <p>
                Failed generations are response attempts explicitly recorded as
                failed or still unfinished after 15 minutes. The rate uses only
                tracked attempts known to be completed, failed, or stuck; recent
                pending attempts and activity from before tracking are excluded.
            </p>
            <p>
                Feedback counts submitted thumbs ratings. Guardrails count retry
                attempts and final blocked responses.
            </p>
            <p>
                Use the Median, P95, Thumbs up, and Thumbs down legend buttons
                to show or hide a series. Select chart values to open available
                details when you have access.
            </p>
        </div>
    </HelpDialog>
);
