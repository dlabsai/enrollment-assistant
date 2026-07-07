import { useNavigate } from "@tanstack/react-router";
import { type JSX, useCallback } from "react";

import { PageHeader } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { DEFAULT_EVAL_REPORTS_SEARCH } from "../lib/reports-search-state";
import { EvalsRunCard } from "./evals-run-card";

export const EvalsPage = (): JSX.Element => {
    const navigate = useNavigate();
    const handleOpenReport = useCallback(
        (reportId: string) => {
            void navigate({
                to: "/eval-reports",
                search: {
                    ...DEFAULT_EVAL_REPORTS_SEARCH,
                    report: reportId,
                },
            });
        },
        [navigate],
    );

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="Eval Runner" />

            <PageSection className="flex min-h-0 flex-1">
                <EvalsRunCard onOpenReport={handleOpenReport} />
            </PageSection>
        </PageShell>
    );
};
