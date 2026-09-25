import { execFileSync } from "node:child_process";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!DOCTYPE html><body></body>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
const { default: mermaid } = await import("mermaid");
mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
const python = process.env.PYTHON || (process.platform === "win32" ? ".venv\\Scripts\\python.exe" : "python");
const source = [
  "import json",
  "from lesson_content import CONCEPT_DIAGRAMS",
  "from skillcoach.lessons import ARCHITECTURES",
  "print(json.dumps([d for ds in CONCEPT_DIAGRAMS.values() for d in ds] + list(ARCHITECTURES.values())))",
].join("; ");
const diagrams = JSON.parse(execFileSync(python, ["-c", source], { encoding: "utf8" }));
for (let i = 0; i < diagrams.length; i++) {
  await mermaid.parse(diagrams[i]);
}
console.log(`Parsed ${diagrams.length} authored Mermaid diagrams locally.`);
