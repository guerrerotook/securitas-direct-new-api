import js from "@eslint/js";
import globals from "globals";
import vitest from "eslint-plugin-vitest";

export default [
  {
    ignores: ["node_modules/**", "coverage/**", ".vitest-cache/**"],
  },
  js.configs.recommended,
  {
    files: ["custom_components/securitas/www/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    linterOptions: {
      reportUnusedDisableDirectives: "off",
    },
    rules: {
      "no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrors: "none",
        },
      ],
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
  {
    files: ["tests-js/**/*.js"],
    plugins: { vitest },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.node, ...vitest.environments.env.globals },
    },
    rules: {
      ...vitest.configs.recommended.rules,
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
];
