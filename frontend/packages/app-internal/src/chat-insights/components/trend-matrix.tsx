import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import {
    type CSSProperties,
    type JSX,
    type KeyboardEvent as ReactKeyboardEvent,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { createPortal } from "react-dom";

import {
    formatLocaleNumber,
    makeLocaleNumberFormatter,
} from "../../lib/number-format";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    type TimeGranularity,
} from "../../lib/time-series";
import type { TrendPoint, TrendRow } from "../types";

type TrendDimension = "topics" | "sources" | "documents";

interface CellCoordinates {
    rowIndex: number;
    pointIndex: number;
}

interface TrendTooltipState {
    details: string[];
    left: number;
    placement: "above" | "below" | "cursor";
    top: number;
}

interface PointerPosition {
    clientX: number;
    clientY: number;
}

const TOOLTIP_GAP = 12;
const VIEWPORT_MARGIN = 8;

const positionTooltipAtPointer = (
    element: HTMLElement,
    { clientX, clientY }: PointerPosition,
): void => {
    const rect = element.getBoundingClientRect();
    const left =
        clientX + TOOLTIP_GAP + rect.width <=
        window.innerWidth - VIEWPORT_MARGIN
            ? clientX + TOOLTIP_GAP
            : clientX - rect.width - TOOLTIP_GAP;
    const top =
        clientY + TOOLTIP_GAP + rect.height <=
        window.innerHeight - VIEWPORT_MARGIN
            ? clientY + TOOLTIP_GAP
            : clientY - rect.height - TOOLTIP_GAP;
    element.style.left = `${Math.max(VIEWPORT_MARGIN, left)}px`;
    element.style.top = `${Math.max(VIEWPORT_MARGIN, top)}px`;
    element.style.transform = "none";
};

const percentFormatter = makeLocaleNumberFormatter({
    style: "percent",
    maximumFractionDigits: 0,
});

interface TrendMatrixProps {
    granularity: TimeGranularity;
    topicRows: TrendRow[];
    sourceRows: TrendRow[];
    documentRows: TrendRow[];
}

const maximumChats = (rows: TrendRow[]): number => {
    let maximum = 0;
    for (const row of rows) {
        for (const point of row.points) {
            maximum = Math.max(maximum, point.chats);
        }
    }
    return maximum;
};

const cellStyle = (value: number, maximum: number): CSSProperties => {
    if (value === 0 || maximum === 0) {
        return { backgroundColor: "var(--muted)" };
    }
    const intensity = Math.max(18, Math.round((value / maximum) * 100));
    return {
        backgroundColor: `color-mix(in oklab, var(--chart-1) ${intensity}%, var(--background))`,
    };
};

const previousChange = (
    points: TrendPoint[],
    index: number,
): string | undefined => {
    const current = points[index]?.chats ?? 0;
    const previous = points[index - 1]?.chats;
    if (previous === undefined) {
        return undefined;
    }
    if (previous === 0) {
        return current === 0 ? "No change" : "New activity";
    }
    const percent = (current - previous) / previous;
    return `${percent >= 0 ? "+" : ""}${percentFormatter.format(percent)} vs previous bucket`;
};

const cellDescription = (
    row: TrendRow,
    point: TrendPoint,
    index: number,
    granularity: TimeGranularity,
): string[] => {
    const details = [
        row.name,
        formatTimeSeriesTooltipLabel(point.bucket_start, granularity),
        `${formatLocaleNumber(point.chats)} ${point.chats === 1 ? "chat" : "chats"}`,
    ];
    if (point.answers > 0) {
        details.push(
            `${formatLocaleNumber(point.answers)} ${point.answers === 1 ? "answer" : "answers"} using documents`,
        );
    }
    details.push(previousChange(row.points, index) ?? "First bucket");
    return details;
};

const boundedCoordinates = (
    rows: TrendRow[],
    coordinates: CellCoordinates,
): CellCoordinates => {
    const rowIndex = Math.max(
        0,
        Math.min(coordinates.rowIndex, Math.max(0, rows.length - 1)),
    );
    const pointCount = rows[rowIndex]?.points.length ?? 0;
    return {
        rowIndex,
        pointIndex: Math.max(
            0,
            Math.min(coordinates.pointIndex, Math.max(0, pointCount - 1)),
        ),
    };
};

const cellId = (
    dimension: TrendDimension,
    rowIndex: number,
    pointIndex: number,
): string => `trend-cell-${dimension}-${rowIndex}-${pointIndex}`;

export const TrendMatrix = ({
    granularity,
    topicRows,
    sourceRows,
    documentRows,
}: TrendMatrixProps): JSX.Element => {
    const [dimension, setDimension] = useState<TrendDimension>("topics");
    const [activeCell, setActiveCell] = useState<CellCoordinates>({
        rowIndex: 0,
        pointIndex: 0,
    });
    const [tooltip, setTooltip] = useState<TrendTooltipState | null>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);
    const pointerPositionRef = useRef<PointerPosition | null>(null);
    const rows = useMemo(() => {
        switch (dimension) {
            case "topics": {
                return topicRows;
            }
            case "sources": {
                return sourceRows;
            }
            case "documents": {
                return documentRows;
            }
            default: {
                return topicRows;
            }
        }
    }, [dimension, documentRows, sourceRows, topicRows]);
    const maximum = useMemo(() => maximumChats(rows), [rows]);
    const bucketCount = rows[0]?.points.length ?? 0;
    const boundedActiveCell = boundedCoordinates(rows, activeCell);

    const showFocusedTooltip = (
        element: HTMLElement,
        details: string[],
    ): void => {
        pointerPositionRef.current = null;
        const rect = element.getBoundingClientRect();
        const availableWidth = Math.max(0, window.innerWidth - 16);
        const tooltipWidth = Math.min(320, availableWidth);
        const left = Math.max(
            8,
            Math.min(
                rect.left + rect.width / 2 - tooltipWidth / 2,
                window.innerWidth - tooltipWidth - 8,
            ),
        );
        const placement = rect.top >= 112 ? "above" : "below";
        setTooltip({
            details,
            left,
            placement,
            top: placement === "above" ? rect.top - 8 : rect.bottom + 8,
        });
    };

    const moveTooltipToPointer = (
        clientX: number,
        clientY: number,
    ): void => {
        const position = { clientX, clientY };
        pointerPositionRef.current = position;
        if (tooltipRef.current !== null) {
            positionTooltipAtPointer(tooltipRef.current, position);
        }
    };

    const showPointerTooltip = (
        clientX: number,
        clientY: number,
        details: string[],
    ): void => {
        pointerPositionRef.current = { clientX, clientY };
        setTooltip({
            details,
            left: clientX + TOOLTIP_GAP,
            placement: "cursor",
            top: clientY + TOOLTIP_GAP,
        });
    };

    useLayoutEffect(() => {
        if (
            tooltip?.placement === "cursor" &&
            tooltipRef.current !== null &&
            pointerPositionRef.current !== null
        ) {
            positionTooltipAtPointer(
                tooltipRef.current,
                pointerPositionRef.current,
            );
        }
    }, [tooltip]);

    const moveFocus = (coordinates: CellCoordinates): void => {
        const next = boundedCoordinates(rows, coordinates);
        setActiveCell(next);
        document
            .querySelector<HTMLElement>(
                `#${cellId(dimension, next.rowIndex, next.pointIndex)}`,
            )
            ?.focus();
    };

    const handleCellKeyDown = (
        event: ReactKeyboardEvent<HTMLDivElement>,
        rowIndex: number,
        pointIndex: number,
    ): void => {
        let next: CellCoordinates | undefined;
        switch (event.key) {
            case "ArrowLeft": {
                next = { rowIndex, pointIndex: pointIndex - 1 };
                break;
            }
            case "ArrowRight": {
                next = { rowIndex, pointIndex: pointIndex + 1 };
                break;
            }
            case "ArrowUp": {
                next = { rowIndex: rowIndex - 1, pointIndex };
                break;
            }
            case "ArrowDown": {
                next = { rowIndex: rowIndex + 1, pointIndex };
                break;
            }
            case "Home": {
                next = { rowIndex, pointIndex: 0 };
                break;
            }
            case "End": {
                next = { rowIndex, pointIndex: bucketCount - 1 };
                break;
            }
            default: {
                return;
            }
        }
        event.preventDefault();
        moveFocus(next);
    };

    return (
        <Card>
            <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex flex-col gap-1.5">
                        <CardTitle>Change over time</CardTitle>
                        <CardDescription>
                            Darker cells represent more distinct chats. Hover a
                            cell or use arrow keys for counts; document cells also
                            include answers that used documents.
                        </CardDescription>
                    </div>
                    <ToggleGroup
                        aria-label="Trend dimension"
                        onValueChange={(value) => {
                            const [next] = value;
                            if (
                                next === "topics" ||
                                next === "sources" ||
                                next === "documents"
                            ) {
                                setDimension(next);
                                setActiveCell({ rowIndex: 0, pointIndex: 0 });
                                pointerPositionRef.current = null;
                                setTooltip(null);
                            }
                        }}
                        value={[dimension]}
                        variant="outline"
                    >
                        <ToggleGroupItem value="topics">
                            Topics
                        </ToggleGroupItem>
                        <ToggleGroupItem value="sources">
                            Sources
                        </ToggleGroupItem>
                        <ToggleGroupItem value="documents">
                            Documents
                        </ToggleGroupItem>
                    </ToggleGroup>
                </div>
            </CardHeader>
            <CardContent>
                {rows.length === 0 || bucketCount === 0 ? (
                    <div className="text-muted-foreground flex h-48 items-center justify-center text-sm">
                        No trend data in this range
                    </div>
                ) : (
                    <>
                        <div
                            className="overflow-x-auto pb-2"
                            onScroll={() => {
                                pointerPositionRef.current = null;
                                setTooltip(null);
                            }}
                        >
                            <div
                                aria-colcount={bucketCount + 1}
                                aria-label={`${dimension} trends`}
                                aria-rowcount={rows.length + 1}
                                className="grid min-w-max gap-1"
                                role="grid"
                                style={{
                                    gridTemplateColumns: `minmax(13rem, 19rem) repeat(${bucketCount}, minmax(2rem, 1fr))`,
                                }}
                            >
                                <div className="contents" role="row">
                                    <div role="columnheader">
                                        <span className="sr-only">Trend</span>
                                    </div>
                                    {rows[0]?.points.map((point, index) => (
                                        <div
                                            className="text-muted-foreground min-h-10 origin-bottom-left -rotate-45 self-end whitespace-nowrap text-xs"
                                            key={point.bucket_start}
                                            role="columnheader"
                                        >
                                            {index %
                                                Math.max(
                                                    1,
                                                    Math.ceil(bucketCount / 8),
                                                ) ===
                                            0
                                                ? formatTimeSeriesTick(
                                                      point.bucket_start,
                                                      granularity,
                                                  )
                                                : ""}
                                        </div>
                                    ))}
                                </div>
                                {rows.map((row, rowIndex) => (
                                    <div
                                        className="contents"
                                        key={row.key}
                                        role="row"
                                    >
                                        <div
                                            className="flex min-h-8 items-center truncate pr-3 text-sm font-medium"
                                            role="rowheader"
                                        >
                                            {row.name}
                                        </div>
                                        {row.points.map((point, pointIndex) => {
                                            const details = cellDescription(
                                                row,
                                                point,
                                                pointIndex,
                                                granularity,
                                            );
                                            const isActive =
                                                boundedActiveCell.rowIndex ===
                                                    rowIndex &&
                                                boundedActiveCell.pointIndex ===
                                                    pointIndex;
                                            return (
                                                <div
                                                    aria-label={details.join(
                                                        ", ",
                                                    )}
                                                    className="focus-visible:ring-ring min-h-8 cursor-crosshair rounded-sm focus-visible:ring-2 focus-visible:outline-none"
                                                    id={cellId(
                                                        dimension,
                                                        rowIndex,
                                                        pointIndex,
                                                    )}
                                                    key={point.bucket_start}
                                                    onBlur={() => {
                                                        setTooltip(null);
                                                    }}
                                                    onFocus={(event) => {
                                                        setActiveCell({
                                                            rowIndex,
                                                            pointIndex,
                                                        });
                                                        showFocusedTooltip(
                                                            event.currentTarget,
                                                            details,
                                                        );
                                                    }}
                                                    onKeyDown={(event) => {
                                                        handleCellKeyDown(
                                                            event,
                                                            rowIndex,
                                                            pointIndex,
                                                        );
                                                    }}
                                                    onPointerEnter={(event) => {
                                                        showPointerTooltip(
                                                            event.clientX,
                                                            event.clientY,
                                                            details,
                                                        );
                                                    }}
                                                    onPointerLeave={() => {
                                                        pointerPositionRef.current =
                                                            null;
                                                        setTooltip(null);
                                                    }}
                                                    onPointerMove={(event) => {
                                                        moveTooltipToPointer(
                                                            event.clientX,
                                                            event.clientY,
                                                        );
                                                    }}
                                                    role="gridcell"
                                                    style={cellStyle(
                                                        point.chats,
                                                        maximum,
                                                    )}
                                                    tabIndex={isActive ? 0 : -1}
                                                />
                                            );
                                        })}
                                    </div>
                                ))}
                            </div>
                        </div>
                        {tooltip !== null &&
                            createPortal(
                                <div
                                    className="bg-popover text-popover-foreground pointer-events-none fixed z-50 w-max max-w-[min(20rem,calc(100vw-1rem))] rounded-md border px-3 py-2 text-sm shadow-md"
                                    ref={tooltipRef}
                                    role="tooltip"
                                    style={{
                                        left: tooltip.left,
                                        top: tooltip.top,
                                        transform:
                                            tooltip.placement === "above"
                                                ? "translateY(-100%)"
                                                : undefined,
                                    }}
                                >
                                    <div className="font-medium">
                                        {tooltip.details[0]}
                                    </div>
                                    <div className="text-muted-foreground mt-0.5 text-xs">
                                        {tooltip.details.slice(1).join(" · ")}
                                    </div>
                                </div>,
                                document.body,
                            )}
                    </>
                )}
            </CardContent>
        </Card>
    );
};
