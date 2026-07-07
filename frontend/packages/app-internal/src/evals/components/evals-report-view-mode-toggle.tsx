import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import type { JSX } from "react";

export type EvalsReportViewMode = "report" | "compare" | "trends" | "models";

interface EvalsReportViewModeToggleProps {
    viewMode: EvalsReportViewMode;
    onViewModeChange: (viewMode: EvalsReportViewMode) => void;
}

const isEvalsReportViewMode = (
    value: string | undefined,
): value is EvalsReportViewMode =>
    value === "report" ||
    value === "compare" ||
    value === "trends" ||
    value === "models";

export const EvalsReportViewModeToggle = ({
    viewMode,
    onViewModeChange,
}: EvalsReportViewModeToggleProps): JSX.Element => (
    <ToggleGroup
        onValueChange={(value) => {
            const [nextValue] = value;
            if (isEvalsReportViewMode(nextValue)) {
                onViewModeChange(nextValue);
            }
        }}
        size="sm"
        value={[viewMode]}
        variant="outline"
    >
        <ToggleGroupItem value="report">Report</ToggleGroupItem>
        <ToggleGroupItem value="compare">Compare</ToggleGroupItem>
        <ToggleGroupItem value="trends">Trends</ToggleGroupItem>
        <ToggleGroupItem value="models">Models</ToggleGroupItem>
    </ToggleGroup>
);
