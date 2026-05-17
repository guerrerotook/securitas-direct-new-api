import { describe, it, expect } from "vitest";
import { escHtml } from "../../custom_components/securitas/www/verisure-owa-card-utils.js";

describe("escHtml", () => {
  it("escapes <, >, &, double quote, single quote", () => {
    expect(escHtml(`<script>alert("x")&'`)).toBe("&lt;script&gt;alert(&quot;x&quot;)&amp;&#39;");
  });

  it("escapes & before other entities to avoid double-escaping", () => {
    expect(escHtml("&lt;")).toBe("&amp;lt;");
  });

  it("returns empty string for empty input", () => {
    expect(escHtml("")).toBe("");
  });

  it("coerces non-string input to string", () => {
    expect(escHtml(123)).toBe("123");
    expect(escHtml(null)).toBe("null");
    expect(escHtml(undefined)).toBe("undefined");
    expect(escHtml(true)).toBe("true");
  });

  it("leaves unicode and plain characters alone", () => {
    expect(escHtml("Hola — Buenos Días 🚨")).toBe("Hola — Buenos Días 🚨");
  });
});
