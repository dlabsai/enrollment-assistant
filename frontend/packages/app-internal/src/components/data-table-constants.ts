export const DATA_TABLE_PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
export type DataTablePageSize = (typeof DATA_TABLE_PAGE_SIZE_OPTIONS)[number];
export const DATA_TABLE_DEFAULT_PAGE_SIZE: DataTablePageSize = 25;
export const getDefaultDataTablePageSize = (): number =>
    DATA_TABLE_DEFAULT_PAGE_SIZE;

export const isDataTablePageSize = (
    value: number | undefined,
): value is DataTablePageSize =>
    value !== undefined &&
    (DATA_TABLE_PAGE_SIZE_OPTIONS as readonly number[]).includes(value);
