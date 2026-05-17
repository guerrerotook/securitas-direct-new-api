import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("runs in a DOM environment", () => {
    const el = document.createElement("div");
    el.textContent = "hello";
    document.body.appendChild(el);
    expect(document.body.querySelector("div").textContent).toBe("hello");
  });
});
