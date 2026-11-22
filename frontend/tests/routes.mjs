// Gate 5 uses the production origin and an installed Chromium browser.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { existsSync } from "node:fs";
const origin = process.env.GATE_ORIGIN ?? "http://localhost:8080";
const executablePath = [
  process.env.CHROMIUM_PATH,
  chromium.executablePath(),
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/chromium",
  "/usr/bin/google-chrome",
].find((p) => p && existsSync(p));
assert.ok(
  executablePath,
  "Set CHROMIUM_PATH to the installed Chromium executable",
);
const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});
try {
  const page = await browser.newPage({ baseURL: origin });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByRole("heading", { name: "Command center", exact: true })
    .waitFor();
  await page.locator("tbody tr a").first().waitFor();
  await page.getByText("Alerts live", { exact: true }).waitFor();
  await page.getByText("Mule live", { exact: true }).waitFor();
  console.log("Command center: real alerts and both live channels");
  await page.goto("/radar");
  await page.locator("canvas").waitFor();
  await page.locator(".scroll button").first().click();
  await page.getByRole("link", { name: "Inspect Form 4" }).waitFor();
  console.log("Radar: WebGL scene, feed selection and filing drilldown");
  await page.goto("/mule");
  await page.locator("canvas").waitFor();
  const ring = await page.locator("select option").nth(1).getAttribute("value");
  assert.ok(ring);
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/rings/" + ring + "/graph") && r.ok(),
    ),
    page.locator("select").first().selectOption(ring),
  ]);
  const input = page.getByRole("slider", { name: "Time window" });
  await input.focus();
  const count = await page.locator(".explorer h2 small").innerText();
  await input.press("Home");
  await page.waitForFunction(
    (v) => document.querySelector(".explorer h2 small")?.textContent !== v,
    count,
  );
  console.log("Mule: WebGL scene, ring isolation and time scrubber");
  if (process.env.GATE_COLD_ACCOUNT) {
    await page.goto("/mule?account=" + process.env.GATE_COLD_ACCOUNT);
    await page.getByText("Low confidence", { exact: true }).waitFor();
    const curve = await (
      await page.request.get("/api/v1/mule/model/metrics")
    ).json();
    for (const ap of Object.values(curve.cold_start.pr_auc)) {
      await page
        .getByRole("cell", { name: ap.toFixed(3), exact: true })
        .first()
        .waitFor();
    }
    console.log(
      "Cold-start badge and four measured PR-AUC values matched the API",
    );
  }
  await page.goto("/research");
  const frame = page.frameLocator("iframe");
  await frame
    .getByRole("heading", { name: "Threshold Tuner", exact: true })
    .waitFor({ timeout: 45000 });
  assert.deepEqual(errors, []);
  console.log("Workbench: live Streamlit iframe rendered through nginx");
} finally {
  await browser.close();
}
