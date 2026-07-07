import { Badge } from "@va/shared/components/ui/badge";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@va/shared/components/ui/table";
import type { JSX } from "react";

import { formatTableTimestamp } from "../../lib/date-format";
import { formatLocaleNumber } from "../../lib/number-format";
import { formatUsageCost, formatUsageDuration } from "../lib/formatters";
import type { UsageTraceBasic } from "../types";

interface UsageTableProps {
    traces: UsageTraceBasic[];
}

const formatTimestamp = formatTableTimestamp;

const formatPlatform = (value: boolean | null): string => {
    if (value === true) {
        return "Public";
    }
    if (value === false) {
        return "Internal";
    }
    return "Unknown";
};

export const UsageTable = ({ traces }: UsageTableProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>Recent requests</CardTitle>
            <CardDescription>Latest {formatLocaleNumber(traces.length)} requests</CardDescription>
        </CardHeader>
        <CardContent className="overflow-hidden px-0">
            <div className="overflow-x-auto px-6">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Time</TableHead>
                            <TableHead>Model</TableHead>
                            <TableHead>Platform</TableHead>
                            <TableHead className="text-right">Tokens</TableHead>
                            <TableHead className="text-right">Cost</TableHead>
                            <TableHead className="text-right">
                                Duration
                            </TableHead>
                            <TableHead>Status</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {traces.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={7}>
                                    No usage data available yet.
                                </TableCell>
                            </TableRow>
                        ) : (
                            traces.map((trace) => {
                                const totalTokens =
                                    (trace.prompt_tokens ?? 0) +
                                    (trace.completion_tokens ?? 0);

                                return (
                                    <TableRow key={trace.created_at}>
                                        <TableCell>
                                            {formatTimestamp(trace.created_at)}
                                        </TableCell>
                                        <TableCell>{trace.model}</TableCell>
                                        <TableCell>
                                            {formatPlatform(trace.is_public)}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">
                                            {formatLocaleNumber(totalTokens)}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">
                                            {formatUsageCost(trace.cost)}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">
                                            {formatUsageDuration(trace.duration)}
                                        </TableCell>
                                        <TableCell>
                                            <Badge
                                                variant={
                                                    trace.is_error
                                                        ? "destructive"
                                                        : "secondary"
                                                }
                                            >
                                                {trace.is_error
                                                    ? "Error"
                                                    : "OK"}
                                            </Badge>
                                        </TableCell>
                                    </TableRow>
                                );
                            })
                        )}
                    </TableBody>
                </Table>
            </div>
        </CardContent>
    </Card>
);
