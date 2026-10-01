import { Badge } from "@va/shared/components/ui/badge";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { Progress } from "@va/shared/components/ui/progress";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@va/shared/components/ui/table";
import { ExternalLink } from "lucide-react";
import type { JSX } from "react";
import { Pie, PieChart } from "recharts";

import {
    type ChartConfig,
    ChartContainer,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { formatTableTimestamp } from "../../lib/date-format";
import {
    formatLocaleNumber,
    makeLocaleNumberFormatter,
} from "../../lib/number-format";
import type {
    GroundedDocumentMetric,
    SourceMetric,
} from "../types";

interface SourcesPanelProps {
    sources: SourceMetric[];
    documents: GroundedDocumentMetric[];
}

const utilizationChartConfig = {
    used: {
        label: "Used in answers",
        color: "var(--chart-1)",
    },
    unused: {
        label: "Not used in answers",
        color: "var(--muted)",
    },
} satisfies ChartConfig;

const percentFormatter = makeLocaleNumberFormatter({
    style: "percent",
    maximumFractionDigits: 1,
});

const documentTypeLabel = (value: string): string => {
    switch (value) {
        case "training_material": {
            return "Training material";
        }
        case "website_page":
        case "catalog_page": {
            return "Web page";
        }
        case "website_program":
        case "catalog_program": {
            return "Program";
        }
        case "catalog_course": {
            return "Course";
        }
        default: {
            return value;
        }
    }
};

export const SourcesPanel = ({
    sources,
    documents,
}: SourcesPanelProps): JSX.Element => {
    const currentDocuments = sources.reduce(
        (total, source) => total + source.current_documents,
        0,
    );
    const currentDocumentsUsed = sources.reduce(
        (total, source) => total + source.current_documents_used,
        0,
    );
    const utilization =
        currentDocuments > 0 ? currentDocumentsUsed / currentDocuments : null;
    const utilizationData = [
        {
            category: "used",
            documents: currentDocumentsUsed,
            fill: "var(--color-used)",
        },
        {
            category: "unused",
            documents: Math.max(
                0,
                currentDocuments - currentDocumentsUsed,
            ),
            fill: "var(--color-unused)",
        },
    ];

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-4">
                <Card>
                    <CardHeader>
                        <CardTitle>Current KB utilization</CardTitle>
                        <CardDescription>
                            Share of current, available documents used in this range
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-col items-center gap-2">
                        <ChartContainer
                            className="h-36 w-full"
                            config={utilizationChartConfig}
                        >
                            <PieChart accessibilityLayer>
                                <ChartTooltip
                                    content={
                                        <ChartTooltipContent nameKey="category" />
                                    }
                                />
                                <Pie
                                    data={utilizationData}
                                    dataKey="documents"
                                    innerRadius={42}
                                    isAnimationActive={false}
                                    nameKey="category"
                                    outerRadius={62}
                                    strokeWidth={2}
                                />
                            </PieChart>
                        </ChartContainer>
                        <div className="text-center">
                            <div className="text-xl font-semibold tabular-nums">
                                {utilization === null
                                    ? "—"
                                    : percentFormatter.format(utilization)}
                            </div>
                            <div className="text-muted-foreground text-xs">
                                {formatLocaleNumber(currentDocumentsUsed)} of{" "}
                                {formatLocaleNumber(currentDocuments)} current documents
                            </div>
                        </div>
                    </CardContent>
                </Card>
                {sources.map((source) => (
                    <Card key={source.key}>
                        <CardHeader>
                            <CardTitle>{source.name}</CardTitle>
                            <CardDescription>
                                {formatLocaleNumber(source.answers)} answers
                                across {formatLocaleNumber(source.chats)} chats
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="flex flex-col gap-3">
                            <div className="flex items-center justify-between gap-3 text-sm">
                                <span>Current KB utilization</span>
                                <span className="font-medium tabular-nums">
                                    {source.utilization === null
                                        ? "—"
                                        : percentFormatter.format(
                                              source.utilization,
                                          )}
                                </span>
                            </div>
                            <Progress
                                aria-label={`${source.name} current knowledge-base utilization`}
                                value={(source.utilization ?? 0) * 100}
                            />
                            <div className="text-muted-foreground text-xs">
                                {formatLocaleNumber(
                                    source.current_documents_used,
                                )}{" "}
                                of{" "}
                                {formatLocaleNumber(source.current_documents)}{" "}
                                current documents available to you were used
                            </div>
                        </CardContent>
                    </Card>
                ))}
            </div>

            <Card>
            <CardHeader>
                <CardTitle>Most used supporting documents</CardTitle>
                <CardDescription>
                    Only documents used to support an answer are counted
                </CardDescription>
            </CardHeader>
            <CardContent className="px-0">
                <Table className="min-w-[64rem] table-fixed">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[28%] whitespace-normal pl-6">
                                Document
                            </TableHead>
                            <TableHead className="w-[12%]">Type</TableHead>
                            <TableHead className="w-[19%]">
                                Document subject
                            </TableHead>
                            <TableHead className="w-[17%]">
                                Document purpose
                            </TableHead>
                            <TableHead className="w-[7%] text-end">
                                Answers
                            </TableHead>
                            <TableHead className="w-[6%] text-end">
                                Chats
                            </TableHead>
                            <TableHead className="w-[11%] pr-6">
                                Last used
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {documents.length === 0 ? (
                            <TableRow>
                                <TableCell
                                    className="text-muted-foreground h-24 text-center"
                                    colSpan={7}
                                >
                                    No supporting documents used in this range
                                </TableCell>
                            </TableRow>
                        ) : (
                            documents.map((document) => (
                                <TableRow key={document.source_key}>
                                    <TableCell className="whitespace-normal pl-6 align-top">
                                        {document.url === "" ? (
                                            <span className="block break-words font-medium">
                                                {document.title}
                                            </span>
                                        ) : (
                                            <a
                                                className="flex min-w-0 items-start gap-1 font-medium whitespace-normal underline-offset-4 hover:underline"
                                                href={document.url}
                                                rel="noreferrer"
                                                target="_blank"
                                            >
                                                <span className="min-w-0 break-words">
                                                    {document.title}
                                                </span>
                                                <ExternalLink
                                                    aria-hidden
                                                    className="mt-0.5 size-3 shrink-0"
                                                />
                                            </a>
                                        )}
                                    </TableCell>
                                    <TableCell className="align-top">
                                        <Badge variant="outline">
                                            {documentTypeLabel(
                                                document.document_type,
                                            )}
                                        </Badge>
                                    </TableCell>
                                    <TableCell className="whitespace-normal align-top">
                                        <div className="flex min-w-0 flex-col items-start gap-1">
                                            <span className="break-words">
                                                {document.primary_subject ??
                                                    "Pending"}
                                            </span>
                                            {document.secondary_subjects.map(
                                                (subject) => (
                                                    <Badge
                                                        className="h-auto max-w-full justify-start break-words whitespace-normal text-left"
                                                        key={subject}
                                                        variant="outline"
                                                    >
                                                        {subject}
                                                    </Badge>
                                                ),
                                            )}
                                        </div>
                                    </TableCell>
                                    <TableCell className="whitespace-normal align-top">
                                        <div className="flex min-w-0 flex-col gap-1">
                                            <span className="break-words">
                                                {document.document_function ??
                                                    "Pending"}
                                            </span>
                                            {document.confidence !== null && (
                                                <span className="text-muted-foreground text-xs capitalize">
                                                    {document.confidence} confidence
                                                </span>
                                            )}
                                        </div>
                                    </TableCell>
                                    <TableCell className="text-end align-top tabular-nums">
                                        {formatLocaleNumber(document.answers)}
                                    </TableCell>
                                    <TableCell className="text-end align-top tabular-nums">
                                        {formatLocaleNumber(document.chats)}
                                    </TableCell>
                                    <TableCell className="pr-6 align-top text-xs tabular-nums">
                                        {formatTableTimestamp(
                                            document.last_used_at,
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </CardContent>
            </Card>
        </div>
    );
};
