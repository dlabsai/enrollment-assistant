import assert from "node:assert/strict";
import test from "node:test";

import { formatUsdCost } from "../src/lib/number-format.ts";

const formatFixed = (value: number, fractionDigits: number): string =>
    value.toLocaleString(undefined, {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
    });

test("formatUsdCost applies the shared USD precision contract", () => {
    assert.equal(formatUsdCost(undefined), "-");
    assert.equal(formatUsdCost(null), "-");
    assert.equal(formatUsdCost(Number.NaN), "-");
    assert.equal(formatUsdCost(0), `$${formatFixed(0, 2)}`);
    assert.equal(formatUsdCost(1.2), `$${formatFixed(1.2, 2)}`);
    assert.equal(formatUsdCost(0.01), `$${formatFixed(0.01, 2)}`);
    assert.equal(formatUsdCost(0.0012), `$${formatFixed(0.0012, 4)}`);
    assert.equal(formatUsdCost(0.0001), `$${formatFixed(0.0001, 4)}`);
    assert.equal(formatUsdCost(0.000_01), `<$${formatFixed(0.0001, 4)}`);
});
