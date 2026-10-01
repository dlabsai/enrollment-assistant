import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { Progress } from "@va/shared/components/ui/progress";
import { Separator } from "@va/shared/components/ui/separator";
import { type JSX, useMemo, useState } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import type {
    RequestTypeMetric,
    TopicMetric,
    TopicPairMetric,
} from "../types";

interface TopicsPanelProps {
    topics: TopicMetric[];
    requestTypes: RequestTypeMetric[];
    pairs: TopicPairMetric[];
}

const requestTypeLabel = (value: string): string =>
    value.replaceAll(/(?:^|\s)\S/gu, (character) => character.toUpperCase());

export const TopicsPanel = ({
    topics,
    requestTypes,
    pairs,
}: TopicsPanelProps): JSX.Element => {
    const [selectedKey, setSelectedKey] = useState(topics[0]?.key ?? "");
    const selected = useMemo(
        () => topics.find((topic) => topic.key === selectedKey) ?? topics[0],
        [selectedKey, topics],
    );
    const maxMentions = Math.max(1, ...topics.map((topic) => topic.mention_chats));
    const requestTotal = requestTypes.reduce(
        (total, item) => total + item.chats,
        0,
    );

    return (
        <div className="grid grid-cols-1 gap-4 @5xl/main:grid-cols-[minmax(0,1.6fr)_minmax(20rem,1fr)]">
            <Card>
                <CardHeader>
                    <CardTitle>Topics in staff questions</CardTitle>
                    <CardDescription>
                        Each chat counts once for every topic it contains. Select
                        a row for its definition and supporting documents.
                    </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                    {topics.map((topic) => (
                        <Button
                            className="h-auto w-full justify-start px-3 py-2"
                            key={topic.key}
                            onClick={() => {
                                setSelectedKey(topic.key);
                            }}
                            variant={
                                selected?.key === topic.key
                                    ? "secondary"
                                    : "ghost"
                            }
                        >
                            <span className="flex min-w-0 flex-1 flex-col gap-1 text-start">
                                <span className="flex items-center justify-between gap-3">
                                    <span className="truncate font-medium">
                                        {topic.name}
                                    </span>
                                    <span className="shrink-0 tabular-nums">
                                        {formatLocaleNumber(
                                            topic.mention_chats,
                                        )}
                                    </span>
                                </span>
                                <Progress
                                    aria-label={`${topic.name}: ${formatLocaleNumber(topic.mention_chats)} chats`}
                                    value={
                                        (topic.mention_chats / maxMentions) *
                                        100
                                    }
                                />
                            </span>
                        </Button>
                    ))}
                </CardContent>
            </Card>

            <div className="flex flex-col gap-4">
                <Card>
                    <CardHeader>
                        <CardTitle>{selected?.name ?? "Topic detail"}</CardTitle>
                        <CardDescription>
                            {selected?.description ??
                                "Run analysis to populate topic details."}
                        </CardDescription>
                    </CardHeader>
                    {selected !== undefined && (
                        <CardContent className="flex flex-col gap-4">
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <div className="text-muted-foreground text-xs">
                                        Chats with this topic
                                    </div>
                                    <div className="text-xl font-semibold tabular-nums">
                                        {formatLocaleNumber(
                                            selected.mention_chats,
                                        )}
                                    </div>
                                </div>
                                <div>
                                    <div className="text-muted-foreground text-xs">
                                        Chats where this is primary
                                    </div>
                                    <div className="text-xl font-semibold tabular-nums">
                                        {formatLocaleNumber(
                                            selected.primary_chats,
                                        )}
                                    </div>
                                </div>
                            </div>
                            <Separator />
                            <div className="flex flex-col gap-2">
                                <div className="text-sm font-medium">
                                    What supporting documents cover
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {selected.top_document_subjects.length ===
                                    0 ? (
                                        <span className="text-muted-foreground text-sm">
                                            No supporting documents used in
                                            this range
                                        </span>
                                    ) : (
                                        selected.top_document_subjects.map(
                                            (subject) => (
                                                <Badge
                                                    key={subject.key}
                                                    variant="secondary"
                                                >
                                                    {subject.name} ·{" "}
                                                    {formatLocaleNumber(
                                                        subject.answers,
                                                    )}
                                                </Badge>
                                            ),
                                        )
                                    )}
                                </div>
                            </div>
                            <div className="flex flex-col gap-2">
                                <div className="text-sm font-medium">
                                    Supporting document purposes
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {selected.top_document_functions.map(
                                        (item) => (
                                            <Badge
                                                key={item.key}
                                                variant="outline"
                                            >
                                                {item.name} ·{" "}
                                                {formatLocaleNumber(
                                                    item.answers,
                                                )}
                                            </Badge>
                                        ),
                                    )}
                                </div>
                            </div>
                        </CardContent>
                    )}
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle>Request types</CardTitle>
                        <CardDescription>
                            The action staff wanted from the assistant
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-col gap-3">
                        {requestTypes
                            .filter((item) => item.chats > 0)
                            .map((item) => (
                                <div
                                    className="flex flex-col gap-1"
                                    key={item.key}
                                >
                                    <div className="flex items-center justify-between gap-3 text-sm">
                                        <span>
                                            {requestTypeLabel(item.name)}
                                        </span>
                                        <span className="tabular-nums">
                                            {formatLocaleNumber(item.chats)}
                                        </span>
                                    </div>
                                    <Progress
                                        aria-label={`${requestTypeLabel(item.name)}: ${formatLocaleNumber(item.chats)} chats`}
                                        value={
                                            requestTotal > 0
                                                ? (item.chats / requestTotal) *
                                                  100
                                                : 0
                                        }
                                    />
                                </div>
                            ))}
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle>Common combinations</CardTitle>
                        <CardDescription>
                            Topics requested together in the same chat
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-col gap-2">
                        {pairs.length === 0 ? (
                            <span className="text-muted-foreground text-sm">
                                No multi-topic combinations in this range
                            </span>
                        ) : (
                            pairs.map((pair) => (
                                <div
                                    className="flex items-center justify-between gap-3 text-sm"
                                    key={`${pair.first_key}:${pair.second_key}`}
                                >
                                    <span>
                                        {pair.first_name} + {pair.second_name}
                                    </span>
                                    <Badge variant="outline">
                                        {formatLocaleNumber(pair.chats)}
                                    </Badge>
                                </div>
                            ))
                        )}
                    </CardContent>
                </Card>
            </div>
        </div>
    );
};
