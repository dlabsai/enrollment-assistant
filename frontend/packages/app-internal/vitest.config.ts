import path from "node:path";

import { createSharedAliases, sharedPlugins } from "@va/shared/vite";
import { defineConfig } from "vitest/config";

const sharedRoot = path.resolve(__dirname, "../shared/src");

export default defineConfig({
    plugins: sharedPlugins(),
    resolve: {
        alias: createSharedAliases({
            appRoot: __dirname,
            sharedRoot,
        }),
    },
    test: {
        environment: "node",
        include: ["tests/**/*.test.ts"],
    },
});
