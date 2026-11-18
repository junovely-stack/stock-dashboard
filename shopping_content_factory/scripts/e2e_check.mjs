// 브라우저 E2E 점검: 콘솔 오류·가로 넘침·CSP 위반·주요 요소 존재 + 스크린샷
// 사용: node scripts/e2e_check.mjs http://localhost:5000 <관리자비밀번호> <스크린샷폴더>
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const [base = "http://localhost:5000", password = "", outDir = "."] = process.argv.slice(2);
const results = [];
const browser = await chromium.launch();
async function check(page, name, url, expectSelectors, width) {
  const errors = [];
  page.removeAllListeners("console");
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  const resp = await page.goto(base + url, { waitUntil: "networkidle" });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const missing = [];
  for (const sel of expectSelectors) { if ((await page.locator(sel).count()) === 0) missing.push(sel); }
  await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: true });
  results.push({ name, status: resp.status(), width, overflow_px: overflow, console_errors: errors, missing });
}
const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
await check(mobile, "landing_index_390", "/", [".ad-bar", ".hero-card", ".demo-bar"], 390);
await check(mobile, "landing_product_390", "/p/demo-001?c=C20261118-01&src=ig", [".notice", ".price", ".buy", "table.specs", "video"], 390);
await check(mobile, "landing_disclosure_390", "/disclosure", [".box"], 390);
const desk = await browser.newPage({ viewport: { width: 1366, height: 768 } });
await check(desk, "landing_product_1366", "/p/demo-001?c=C20261118-01", [".product-top"], 1366);
await desk.goto(base + "/admin/login");
await desk.fill("input[name=password]", password);
await desk.fill("input[name=name]", "e2e");
await desk.click("button");
await check(desk, "admin_dashboard", "/admin/", [".pipeline", ".kpi"], 1366);
await check(desk, "admin_candidates", "/admin/candidates?date=2026-11-18", ["progress.bar"], 1366);
await check(desk, "admin_content", "/admin/contents/C20261118-01", ["video.preview", ".media-row img"], 1366);
await check(desk, "admin_finance", "/admin/finance", [".kpi"], 1366);
await check(desk, "admin_analytics", "/admin/analytics", ["table"], 1366);
await check(desk, "admin_logs", "/admin/logs", ["table"], 1366);
// 공개 이벤트 기록 확인 (page_view 가 남았는지)
await browser.close();
console.log(JSON.stringify(results, null, 1));
const bad = results.filter((r) => r.status !== 200 || r.console_errors.length || r.missing.length || r.overflow_px > 0);
process.exit(bad.length ? 1 : 0);
