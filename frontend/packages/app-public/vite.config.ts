import path from "node:path";

import { createSharedAliases, sharedPlugins } from "@va/shared/vite";
import type { MinifyOptions } from "terser";
import { defineConfig, type LibraryFormats, loadEnv } from "vite";
import { analyzer } from "vite-bundle-analyzer";

export default defineConfig(({ command, mode }) => {
    const env = loadEnv(mode, process.cwd(), "");
    const parts = mode.split("-");
    const environmentName = parts[1] || "local";
    const rawEnvironment = environmentName.toLowerCase();
    const normalizedEnvironment = ["local", "stage", "prod"].includes(
        rawEnvironment,
    )
        ? rawEnvironment
        : "local";
    const outDirectory = path.resolve(
        __dirname,
        `../../dist-public-${normalizedEnvironment}`,
    );
    const shouldAnalyze =
        env.VITE_BUNDLE_ANALYZE === "1" || env.VITE_BUNDLE_ANALYZE === "true";

    const base = env.VITE_PUBLIC_WIDGET_BASE_PATH || "/chat-widget/";

    const nodeEnv = command === "build" ? "production" : "development";
    const sharedRoot = path.resolve(__dirname, "../shared/src");
    const terserOptions: MinifyOptions | undefined = undefined;

    return {
        appType: "mpa",
        plugins: [
            ...sharedPlugins(),
            ...(command === "build" && shouldAnalyze
                ? [
                      analyzer({
                          analyzerMode: "json",
                          fileName: `bundle-analysis-public-${normalizedEnvironment}`,
                          summary: false,
                      }),
                  ]
                : []),
        ],
        resolve: {
            alias: createSharedAliases({
                appRoot: __dirname,
                sharedRoot,
            }),
        },
        define: {
            __APP_ENV__: JSON.stringify(normalizedEnvironment),
            __APP_FLAVOR__: JSON.stringify("public"),
            "process.env.NODE_ENV": JSON.stringify(nodeEnv),
        },
        publicDir: path.resolve(__dirname, "../shared/public"),
        base,
        ...(command === "build"
            ? {
                  build: {
                      lib: {
                          entry: path.resolve(__dirname, "./src/main.tsx"),
                          name: "ChatWidget",
                          fileName: (): string => "chat-widget.js",
                          formats: ["iife"] as LibraryFormats[],
                      },
                      outDir: outDirectory,
                      emptyOutDir: true,
                      cssCodeSplit: false,
                      minify: "terser" as const,
                      terserOptions,
                  },
              }
            : {
                  server: {
                      host: "0.0.0.0",
                      port: 5173,
                      cors: true,
                      open: false,
                      watch: {
                          usePolling: true,
                          interval: 500,
                      },
                  },
              }),
    };
});
