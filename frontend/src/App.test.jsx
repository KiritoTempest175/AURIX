import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import App from "./App.jsx";

describe("AURIX desktop onboarding", () => {
  it("renders native configuration entry points and direct app actions", () => {
    const markup = renderToStaticMarkup(<App />);
    expect(markup).toContain("Email");
    expect(markup).toContain("Models");
    expect(markup).toContain("Open WhatsApp");
    expect(markup).toContain("Open calculator");
    expect(markup).toContain("Start microphone transcription");
    expect(markup).toContain("Retry worker");
  });

  it("keeps independent scrolling for main workspace and diagnostics", () => {
    const stylesheet = readFileSync(fileURLToPath(new URL("./App.css", import.meta.url)), "utf8");
    expect(stylesheet).toMatch(/\.stage\s*\{[\s\S]*?overflow-x:\s*hidden;\s*overflow-y:\s*auto;/);
    expect(stylesheet).toMatch(/\.side\s*\{[\s\S]*?overflow-y:\s*auto;/);
    expect(stylesheet).toContain("prefers-reduced-motion");
  });
});
