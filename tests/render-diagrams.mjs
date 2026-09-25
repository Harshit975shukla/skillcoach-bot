// Reuse one local browser/page to avoid repeated Windows startup/navigation timeouts.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const python = process.env.PYTHON || (process.platform === "win32" ? ".venv\\Scripts\\python.exe" : "python");
const source = [
  "import json",
  "from lesson_content import CONCEPT_DIAGRAMS",
  "from skillcoach.lessons import ARCHITECTURES",
  "print(json.dumps([d for ds in CONCEPT_DIAGRAMS.values() for d in ds] + list(ARCHITECTURES.values())))",
].join("; ");
const diagrams = JSON.parse(execFileSync(python, ["-c", source], { encoding: "utf8" }));
const browser = await puppeteer.launch({
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  headless: true,
  args: process.platform === "linux" ? ["--no-sandbox"] : [],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
  await page.setRequestInterception(true);
  page.on("request", request => {
    const protocol = new URL(request.url()).protocol;
    if (["http:", "https:"].includes(protocol)) request.abort();
    else request.continue();
  });
  await page.setContent("<!DOCTYPE html><html><body><div id='diagram'></div></body></html>");
  await page.addScriptTag({ path: fileURLToPath(import.meta.resolve("mermaid/dist/mermaid.min.js")) });
  await page.evaluate(() => window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict" }));
  for (let index = 0; index < diagrams.length; index++) {
    const dimensions = await page.evaluate(async ({ code, index }) => {
      const target = document.getElementById("diagram");
      target.innerHTML = "";
      const { svg } = await window.mermaid.render(`diagram-${index}`, code);
      target.innerHTML = svg;
      const bounds = target.querySelector("svg").getBoundingClientRect();
      return { width: bounds.width, height: bounds.height };
    }, { code: diagrams[index], index });
    if (dimensions.width <= 0 || dimensions.height <= 0) {
      throw new Error(`Diagram ${index + 1} has no rendered dimensions`);
    }
    const screenshot = await (await page.$("#diagram")).screenshot({ type: "png" });
    if (screenshot.length < 100) throw new Error(`Diagram ${index + 1} produced an empty screenshot`);
    console.log(`Rendered and screenshot-verified ${index + 1}/${diagrams.length}`);
  }
} finally {
  await browser.close();
}
console.log(`All ${diagrams.length} authored diagrams rendered locally with external HTTP blocked.`);
