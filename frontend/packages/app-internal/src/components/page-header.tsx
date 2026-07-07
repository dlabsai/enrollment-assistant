import { cn } from "@va/shared/lib/utils";
import type { JSX, ReactNode } from "react";

interface PageHeaderProps {
    title: string;
    children?: ReactNode;
    className?: string;
    titleAddon?: ReactNode;
}

export const PageHeader = ({
    title,
    children,
    className,
    titleAddon,
}: PageHeaderProps): JSX.Element => (
    <div
        className={cn(
            "flex min-h-8 flex-wrap items-center justify-between gap-3 px-4 lg:px-6",
            className,
        )}
    >
        <div className="flex min-h-8 flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">{title}</h2>
            {titleAddon}
        </div>
        {children !== undefined && (
            <div className="flex min-h-8 flex-wrap items-center gap-2">
                {children}
            </div>
        )}
    </div>
);

interface PageHeaderGroupProps {
    children: ReactNode;
    className?: string;
}

export const PageHeaderGroup = ({
    children,
    className,
}: PageHeaderGroupProps): JSX.Element => (
    <div className={cn("flex min-h-8 flex-wrap items-center gap-2", className)}>
        {children}
    </div>
);
