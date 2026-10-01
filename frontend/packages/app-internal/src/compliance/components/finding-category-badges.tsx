import { Badge } from "@va/shared/components/ui/badge";
import type { JSX } from "react";

import { findingCategoryLabel } from "../lib/presentation";
import type { FindingCategory } from "../types";

export const FindingCategoryBadges = ({
    categories,
}: {
    categories: FindingCategory[] | null;
}): JSX.Element => (
    <div
        aria-label="Categories"
        className="flex flex-wrap gap-1"
    >
        {categories === null ? (
            <Badge variant="outline">Not categorized</Badge>
        ) : (
            categories.map((category) => (
                <Badge
                    key={category}
                    variant="outline"
                >
                    {findingCategoryLabel(category)}
                </Badge>
            ))
        )}
    </div>
);
