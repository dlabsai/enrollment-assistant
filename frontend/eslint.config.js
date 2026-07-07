import { fixupConfigRules } from "@eslint/compat";
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import { importX } from "eslint-plugin-import-x";
import react from "eslint-plugin-react";
import reactDom from "eslint-plugin-react-dom";
import reactHooks from "eslint-plugin-react-hooks";
import reactNamingConvention from "eslint-plugin-react-naming-convention";
import reactRefresh from "eslint-plugin-react-refresh";
import reactX from "eslint-plugin-react-x";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import eslintPluginUnicorn from "eslint-plugin-unicorn";
import globals from "globals";
import tseslint from "typescript-eslint";

const jsxTsFiles = ["**/*.{ts,tsx}"];

const reactCompatConfigs = fixupConfigRules(react.configs.flat.all).map(
    (config) => ({
        ...config,
        files: jsxTsFiles,
    }),
);

const reactHooksCompatConfigs = fixupConfigRules(
    reactHooks.configs.flat["recommended-latest"],
).map((config) => ({
    ...config,
    files: jsxTsFiles,
}));

export default defineConfig([
    globalIgnores([
        "packages/shared/src/components/ui",
        "packages/shared/src/components/ai-elements",
        "packages/app-internal/src/components/ui",
    ]),
    ...reactCompatConfigs,
    ...reactHooksCompatConfigs,
    {
        files: jsxTsFiles,
        extends: [
            js.configs.all,
            tseslint.configs.all,
            reactX.configs["strict-type-checked"],
            reactDom.configs.strict,
            reactRefresh.configs.vite,
            reactNamingConvention.configs.recommended,
            importX.configs["flat/recommended"],
            importX.configs["flat/react"],
            eslintPluginUnicorn.configs.all,
        ],
        languageOptions: {
            ecmaVersion: 2022,
            globals: globals.browser,
            parserOptions: {
                project: [
                    "./packages/app-public/tsconfig.node.json",
                    "./packages/app-public/tsconfig.app.json",
                    "./packages/app-internal/tsconfig.node.json",
                    "./packages/app-internal/tsconfig.app.json",
                    "./packages/shared/tsconfig.json",
                ],
                tsconfigRootDir: import.meta.dirname,
            },
        },
        settings: {
            react: {
                version: "detect",
            },
            "import-x/resolver": {
                typescript: {
                    alwaysTryTypes: true,
                    project: "./tsconfig.imports.json",
                },
            },
        },
        plugins: {
            "simple-import-sort": simpleImportSort,
        },
        rules: {
            "@typescript-eslint/switch-exhaustiveness-check": "off",
            "react-naming-convention/context-name": "error",
            "react-naming-convention/id-name": "error",
            "react-naming-convention/ref-name": "error",
            // js.configs.all
            camelcase: "off",
            "capitalized-comments": "off",
            complexity: "off",
            "function-call-argument-newline": "off", // Prettier handles formatting.
            "function-paren-newline": "off", // Prettier handles formatting.
            indent: "off", // Prettier handles formatting.
            "max-depth": "off",
            "max-lines": "off",
            "max-lines-per-function": "off",
            "max-params": "off",
            "max-statements": "off",
            "multiline-ternary": "off", // Prettier handles formatting.
            "no-magic-numbers": "off",
            "no-shadow": "off",
            "no-ternary": "off",
            "no-undefined": "off",
            "no-underscore-dangle": "off",
            "no-void": "off",
            "no-warning-comments": "off",
            "one-var": "off",
            "sort-imports": "off",
            "sort-keys": "off",
            // tseslint.configs.all
            "@typescript-eslint/max-params": "off",
            "@typescript-eslint/naming-convention": "off",
            "@typescript-eslint/no-magic-numbers": "off",
            "@typescript-eslint/no-shadow": "off",
            "@typescript-eslint/no-unnecessary-condition": "off",
            "@typescript-eslint/prefer-readonly-parameter-types": "off",
            // react.configs.flat.all,
            "react/forbid-component-props": "off",
            "react/function-component-definition": "off",
            "react/jsx-child-element-spacing": "off",
            "react/jsx-curly-newline": "off", // Prettier handles formatting.
            "react/jsx-filename-extension": "off",
            "react/jsx-first-prop-new-line": "off",
            "react/jsx-indent": "off", // Prettier handles formatting.
            "react/jsx-max-depth": "off",
            "react/jsx-max-props-per-line": "off",
            "react/jsx-newline": "off",
            "react/jsx-no-bind": "off",
            "react/jsx-no-leaked-render": "off",
            "react/jsx-no-literals": "off",
            "react/jsx-one-expression-per-line": "off",
            "react/jsx-props-no-spreading": "off",
            "react/no-multi-comp": "off",
            "react/no-unescaped-entities": "off",
            "react/prefer-read-only-props": "off",
            "react/react-in-jsx-scope": "off",
            "react/require-default-props": "off",
            // simple-import-sort
            "simple-import-sort/imports": "error",
            "simple-import-sort/exports": "error",
            // eslintPluginUnicorn.configs.all,
            "unicorn/no-keyword-prefix": "off",
            "unicorn/no-null": "off", // Allow null where library callback types use it.
            "unicorn/no-nested-ternary": "off", // Prettier handles formatting.
            "unicorn/prefer-global-this": "off",
            "unicorn/prevent-abbreviations": "off",
        },
    },
]);
