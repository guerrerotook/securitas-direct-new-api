import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "happy-dom",
    globals: false,
    setupFiles: ["./tests-js/setup.js"],
    include: ["tests-js/**/*.test.js"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      include: ["custom_components/securitas/www/**/*.js"],
      exclude: [
        // Legacy securitas-* shim files re-export the canonical verisure-owa-* cards.
        // Globbed so future shims are excluded by convention.
        "custom_components/securitas/www/securitas-*.js",
      ],
      thresholds: {
        lines: 90,
        branches: 90,
        functions: 90,
        statements: 90,
      },
    },
  },
});
