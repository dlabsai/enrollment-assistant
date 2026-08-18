import type {
    ColumnDef,
    OnChangeFn,
    VisibilityState,
} from "@tanstack/react-table";
import { Button } from "@va/shared/components/ui/button";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuTrigger,
} from "@va/shared/components/ui/dropdown-menu";
import { ChevronDown } from "lucide-react";
import type { JSX } from "react";

interface DataTableColumnVisibilityProps<TData> {
    columns: ColumnDef<TData>[];
    columnVisibility: VisibilityState;
    onColumnVisibilityChange: OnChangeFn<VisibilityState>;
}

export const DataTableColumnVisibility = <TData,>({
    columns,
    columnVisibility,
    onColumnVisibilityChange,
}: DataTableColumnVisibilityProps<TData>): JSX.Element => (
    <DropdownMenu>
        <DropdownMenuTrigger
            render={
                <Button variant="outline">
                    Columns
                    <ChevronDown data-icon="inline-end" />
                </Button>
            }
        />
        <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuGroup>
                {columns.map((column) => {
                    const { enableHiding, header, id } = column;
                    if (
                        id === undefined ||
                        enableHiding === false ||
                        typeof header !== "string"
                    ) {
                        return null;
                    }

                    return (
                        <DropdownMenuCheckboxItem
                            checked={columnVisibility[id] ?? true}
                            key={id}
                            onCheckedChange={(checked) => {
                                onColumnVisibilityChange((current) => ({
                                    ...current,
                                    [id]: checked,
                                }));
                            }}
                        >
                            {header}
                        </DropdownMenuCheckboxItem>
                    );
                })}
            </DropdownMenuGroup>
        </DropdownMenuContent>
    </DropdownMenu>
);
