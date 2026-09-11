import * as React from "react";
import * as RechartsPrimitive from "recharts";

import { cn } from "@va/shared/lib/utils";

import { formatLocaleNumber } from "../../lib/number-format";

// Format: { THEME_NAME: CSS_SELECTOR }
const THEMES = { light: "", dark: ".dark" } as const;

export type ChartConfig = Record<
    string,
    {
        label?: React.ReactNode;
        icon?: React.ComponentType;
    } & (
        | { color?: string; theme?: never }
        | { color?: never; theme: Record<keyof typeof THEMES, string> }
    )
>;

interface ChartContextProps {
    config: ChartConfig;
}

interface ChartCategoryCursorProps {
    direction?: "horizontal" | "vertical";
    height?: number;
    width?: number;
    x?: number;
    y?: number;
}

interface ChartInteractiveBarProps {
    canActivate: boolean;
    fill?: string;
    getActionLabel: (index: number) => string | undefined;
    height?: number;
    index?: number;
    itemCount: number;
    onActivate: (index: number) => void;
    width?: number;
    x?: number;
    y?: number;
}

function ChartInteractiveBar({
    canActivate,
    fill,
    getActionLabel,
    height: barHeight,
    index,
    itemCount,
    onActivate,
    width: barWidth,
    x: barX,
    y: barY,
}: ChartInteractiveBarProps) {
    const plotArea = RechartsPrimitive.usePlotArea();
    if (
        barHeight === undefined ||
        barWidth === undefined ||
        barX === undefined ||
        barY === undefined ||
        index === undefined ||
        plotArea === undefined ||
        itemCount === 0 ||
        index < 0 ||
        index >= itemCount
    ) {
        return null;
    }

    const categoryWidth = plotArea.width / itemCount;
    const categoryX = plotArea.x + categoryWidth * index;
    const actionLabel = canActivate ? getActionLabel(index) : undefined;
    const interactive = canActivate && actionLabel !== undefined;
    const activate = (): void => {
        if (interactive) {
            onActivate(index);
        }
    };
    const handleKeyDown = (
        event: React.KeyboardEvent<SVGRectElement>,
    ): void => {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }
        event.preventDefault();
        activate();
    };

    return (
        <g>
            <rect
                aria-hidden="true"
                fill={fill}
                height={barHeight}
                pointerEvents="none"
                rx={4}
                ry={4}
                width={barWidth}
                x={barX}
                y={barY}
            />
            <rect
                aria-label={actionLabel}
                className={
                    interactive
                        ? "focus-visible:stroke-ring cursor-pointer stroke-transparent focus-visible:outline-none"
                        : undefined
                }
                fill="transparent"
                height={plotArea.height}
                onClick={activate}
                onKeyDown={handleKeyDown}
                pointerEvents={interactive ? "all" : "none"}
                role={interactive ? "button" : undefined}
                strokeWidth={2}
                tabIndex={interactive ? 0 : undefined}
                width={categoryWidth}
                x={categoryX}
                y={plotArea.y}
            />
        </g>
    );
}

interface ChartInteractivePointProps extends Pick<
    ChartInteractiveBarProps,
    "canActivate" | "getActionLabel" | "index" | "itemCount" | "onActivate"
> {
    cx?: number;
    cy?: number;
    markerColor?: string;
}

function ChartInteractivePoint({
    canActivate,
    cx,
    cy,
    getActionLabel,
    index,
    itemCount,
    onActivate,
    markerColor,
}: ChartInteractivePointProps) {
    if (
        cx === undefined ||
        cy === undefined ||
        index === undefined ||
        index < 0 ||
        index >= itemCount
    )
        return null;
    if (!canActivate) {
        return markerColor === undefined ? null : (
            <circle
                cx={cx}
                cy={cy}
                fill={markerColor}
                r={6}
            />
        );
    }
    const actionLabel = getActionLabel(index);
    if (actionLabel === undefined) return null;
    return (
        <circle
            aria-label={actionLabel}
            className="focus-visible:stroke-ring stroke-transparent focus-visible:outline-none"
            cx={cx}
            cy={cy}
            fill={markerColor ?? "transparent"}
            onClick={(event) => {
                event.stopPropagation();
                onActivate(index);
            }}
            onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    event.stopPropagation();
                    onActivate(index);
                }
            }}
            r={6}
            role="button"
            strokeWidth={2}
            tabIndex={0}
        />
    );
}

function ChartCategoryCursor({
    direction = "vertical",
    height,
    width,
    x,
    y,
}: ChartCategoryCursorProps) {
    if (
        height === undefined ||
        width === undefined ||
        x === undefined ||
        y === undefined
    ) {
        return null;
    }

    if (direction === "horizontal") {
        const centerY = y + height / 2;
        return (
            <line
                className="stroke-border"
                pointerEvents="none"
                x1={x}
                x2={x + width}
                y1={centerY}
                y2={centerY}
            />
        );
    }

    const centerX = x + width / 2;
    return (
        <line
            className="stroke-border"
            pointerEvents="none"
            x1={centerX}
            x2={centerX}
            y1={y}
            y2={y + height}
        />
    );
}

const ChartContext = React.createContext<ChartContextProps | null>(null);

function useChart() {
    const context = React.use(ChartContext);

    if (!context) {
        throw new Error("useChart must be used within a <ChartContainer />");
    }

    return context;
}

function ChartContainer({
    id,
    className,
    children,
    config,
    ...props
}: React.ComponentProps<"div"> & {
    config: ChartConfig;
    children: React.ComponentProps<
        typeof RechartsPrimitive.ResponsiveContainer
    >["children"];
}) {
    const uniqueId = React.useId();
    const chartId = `chart-${id || uniqueId.replaceAll(":", "")}`;

    return (
        <ChartContext value={{ config }}>
            <div
                className={cn(
                    "[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-grid_line[stroke='#ccc']]:stroke-border/50 [&_.recharts-curve.recharts-tooltip-cursor]:stroke-border [&_.recharts-polar-grid_[stroke='#ccc']]:stroke-border [&_.recharts-radial-bar-background-sector]:fill-muted [&_.recharts-rectangle.recharts-tooltip-cursor]:fill-muted [&_.recharts-reference-line_[stroke='#ccc']]:stroke-border flex aspect-video justify-center text-xs [&_.recharts-dot[stroke='#fff']]:stroke-transparent [&_.recharts-layer]:outline-hidden [&_.recharts-sector]:outline-hidden [&_.recharts-sector[stroke='#fff']]:stroke-transparent [&_.recharts-surface]:outline-hidden",
                    className,
                )}
                data-chart={chartId}
                data-slot="chart"
                {...props}
            >
                <ChartStyle
                    config={config}
                    id={chartId}
                />
                <RechartsPrimitive.ResponsiveContainer>
                    {children}
                </RechartsPrimitive.ResponsiveContainer>
            </div>
        </ChartContext>
    );
}

const ChartStyle = ({ id, config }: { id: string; config: ChartConfig }) => {
    const colorConfig = Object.entries(config).filter(
        ([, config]) => config.theme || config.color,
    );

    if (colorConfig.length === 0) {
        return null;
    }

    return (
        <style
            dangerouslySetInnerHTML={{
                __html: Object.entries(THEMES)
                    .map(
                        ([theme, prefix]) => `
${prefix} [data-chart=${id}] {
${colorConfig
    .map(([key, itemConfig]) => {
        const color =
            itemConfig.theme?.[theme as keyof typeof itemConfig.theme] ||
            itemConfig.color;
        return color ? `  --color-${key}: ${color};` : null;
    })
    .join("\n")}
}
`,
                    )
                    .join("\n"),
            }}
        />
    );
};

const ChartTooltip = RechartsPrimitive.Tooltip;

type ChartPayloadItem = {
    color?: string;
    dataKey?: string | number;
    name?: string;
    payload?: Record<string, unknown>;
    type?: string;
    unit?: React.ReactNode;
    value?: number | string | null;
} & Record<string, unknown>;

interface ChartTooltipContentProps extends React.ComponentProps<"div"> {
    active?: boolean;
    payload?: ChartPayloadItem[];
    indicator?: "line" | "dot" | "dashed";
    hideLabel?: boolean;
    hideIndicator?: boolean;
    label?: React.ReactNode;
    labelFormatter?: (
        label: React.ReactNode,
        payload: ChartPayloadItem[],
    ) => React.ReactNode;
    valueFormatter?: (value: number | string) => React.ReactNode;
    footerFormatter?: (payload: ChartPayloadItem[]) => React.ReactNode;
    color?: string;
    labelClassName?: string;
    nameKey?: string;
    labelKey?: string;
}

function ChartTooltipContent({
    active,
    payload,
    className,
    indicator = "dot",
    hideLabel = false,
    hideIndicator = false,
    label,
    labelFormatter,
    labelClassName,
    valueFormatter,
    footerFormatter,
    color,
    nameKey,
    labelKey,
}: ChartTooltipContentProps) {
    const { config } = useChart();
    const items = payload?.filter(
        (item) =>
            item.type !== "none" &&
            item.value !== undefined &&
            item.value !== null,
    );
    if (!active || !items?.length) {
        return null;
    }

    const [firstItem] = items;
    const headingKey = `${labelKey || firstItem.dataKey || firstItem.name || "value"}`;
    const headingConfig = getPayloadConfigFromPayload(
        config,
        firstItem,
        headingKey,
    );
    const headingValue =
        !labelKey && (typeof label === "string" || typeof label === "number")
            ? (config[String(label)]?.label ?? label)
            : headingConfig?.label;
    const heading = hideLabel
        ? undefined
        : labelFormatter
          ? labelFormatter(headingValue, items)
          : headingValue;
    const footer = footerFormatter?.(items);

    return (
        <div
            className={cn(
                "border-border/50 bg-background grid min-w-[8rem] items-start gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl",
                className,
            )}
            data-slot="chart-tooltip"
        >
            {heading !== undefined && heading !== null && heading !== "" && (
                <div
                    className={cn("font-medium", labelClassName)}
                    data-slot="chart-tooltip-heading"
                >
                    {heading}
                </div>
            )}
            <div className="grid gap-1.5">
                {items.map((item, index) => {
                    const key = `${nameKey || item.name || item.dataKey || "value"}`;
                    const itemConfig = getPayloadConfigFromPayload(
                        config,
                        item,
                        key,
                    );
                    const payloadFill =
                        typeof item.payload?.fill === "string"
                            ? item.payload.fill
                            : undefined;
                    const indicatorColor = color || payloadFill || item.color;
                    return (
                        <div
                            className="flex w-full items-center gap-2"
                            data-slot="chart-tooltip-row"
                            key={String(item.dataKey ?? index)}
                        >
                            {!hideIndicator && (
                                <span
                                    aria-hidden="true"
                                    className="flex size-2.5 shrink-0 items-center justify-center [&>svg]:size-2.5"
                                    data-slot="chart-tooltip-indicator"
                                >
                                    {itemConfig?.icon ? (
                                        <itemConfig.icon />
                                    ) : (
                                        <span
                                            className={cn("rounded-[2px]", {
                                                "size-2.5 bg-current":
                                                    indicator === "dot",
                                                "h-0.5 w-full bg-current":
                                                    indicator === "line",
                                                "w-full border-t-[1.5px] border-dashed border-current":
                                                    indicator === "dashed",
                                            })}
                                            style={{ color: indicatorColor }}
                                        />
                                    )}
                                </span>
                            )}
                            <span
                                className="text-muted-foreground"
                                data-slot="chart-tooltip-label"
                            >
                                {itemConfig?.label ?? item.name ?? item.dataKey}
                            </span>
                            <span
                                className="text-foreground ml-auto pl-4 text-right font-mono font-medium whitespace-nowrap tabular-nums"
                                data-slot="chart-tooltip-value"
                            >
                                {item.value !== undefined &&
                                    item.value !== null &&
                                    (valueFormatter
                                        ? valueFormatter(item.value)
                                        : typeof item.value === "number"
                                          ? formatLocaleNumber(item.value)
                                          : item.value)}
                                {item.unit}
                            </span>
                        </div>
                    );
                })}
            </div>
            {footer !== undefined && footer !== null && footer !== "" && (
                <div
                    className="text-muted-foreground"
                    data-slot="chart-tooltip-footer"
                >
                    {footer}
                </div>
            )}
        </div>
    );
}

const ChartLegend = RechartsPrimitive.Legend;

interface ChartLegendContentProps extends React.ComponentProps<"div"> {
    hiddenKeys?: ReadonlySet<string>;
    hideIcon?: boolean;
    onItemToggle?: (key: string) => void;
    payload?: ChartPayloadItem[];
    verticalAlign?: "top" | "bottom" | "middle";
    nameKey?: string;
}

function ChartLegendContent({
    className,
    hiddenKeys,
    hideIcon = false,
    onItemToggle,
    payload,
    verticalAlign = "bottom",
    nameKey,
}: ChartLegendContentProps) {
    const { config } = useChart();

    if (!payload?.length) {
        return null;
    }

    return (
        <div
            className={cn(
                "flex items-center justify-center gap-4",
                verticalAlign === "top" ? "pb-3" : "pt-3",
                className,
            )}
        >
            {payload
                .filter((item) => item.type !== "none")
                .map((item) => {
                    const key = `${nameKey || item.dataKey || "value"}`;
                    const itemConfig = getPayloadConfigFromPayload(
                        config,
                        item,
                        key,
                    );

                    const hidden = hiddenKeys?.has(key) ?? false;
                    const itemClassName = cn(
                        "[&>svg]:text-muted-foreground flex items-center gap-1.5 [&>svg]:h-3 [&>svg]:w-3",
                        onItemToggle !== undefined &&
                            "cursor-pointer rounded-sm bg-transparent p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                        hidden && "opacity-40",
                    );
                    const content = (
                        <>
                            {itemConfig?.icon && !hideIcon ? (
                                <itemConfig.icon />
                            ) : (
                                <div
                                    className="h-2 w-2 shrink-0 rounded-[2px]"
                                    style={{
                                        backgroundColor: item.color,
                                    }}
                                />
                            )}
                            {itemConfig?.label}
                        </>
                    );

                    return onItemToggle === undefined ? (
                        <div
                            className={itemClassName}
                            key={item.value}
                        >
                            {content}
                        </div>
                    ) : (
                        <button
                            aria-pressed={!hidden}
                            className={itemClassName}
                            key={item.value}
                            onClick={(event) => {
                                event.stopPropagation();
                                onItemToggle(key);
                            }}
                            type="button"
                        >
                            {content}
                        </button>
                    );
                })}
        </div>
    );
}

// Helper to extract item config from a payload.
function getPayloadConfigFromPayload(
    config: ChartConfig,
    payload: unknown,
    key: string,
) {
    if (typeof payload !== "object" || payload === null) {
        return;
    }

    const payloadPayload =
        "payload" in payload &&
        typeof payload.payload === "object" &&
        payload.payload !== null
            ? payload.payload
            : undefined;

    let configLabelKey: string = key;

    if (
        key in payload &&
        typeof payload[key as keyof typeof payload] === "string"
    ) {
        configLabelKey = payload[key as keyof typeof payload] as string;
    } else if (
        payloadPayload &&
        key in payloadPayload &&
        typeof payloadPayload[key as keyof typeof payloadPayload] === "string"
    ) {
        configLabelKey = payloadPayload[
            key as keyof typeof payloadPayload
        ] as string;
    }

    return configLabelKey in config ? config[configLabelKey] : config[key];
}

export {
    ChartCategoryCursor,
    ChartInteractiveBar,
    ChartInteractivePoint,
    ChartContainer,
    ChartLegend,
    ChartLegendContent,
    ChartStyle,
    ChartTooltip,
    ChartTooltipContent,
};
