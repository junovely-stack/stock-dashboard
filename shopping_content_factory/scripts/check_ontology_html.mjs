// 온톨로지 HTML 점검: 콘솔 오류, 노드 글자 넘침, 노드 겹침, viewBox 이탈, 관계 라벨 겹침(노드별 선택),
// 가로 넘침(1366·390), 탭·드로어 동작, 인쇄 모드. 사용: node scripts/check_ontology_html.mjs <html> <스크린샷폴더>
import { createRequire } from "module";
import { pathToFileURL } from "url";
import path from "path";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const [file, outDir = "."] = process.argv.slice(2);
const url = pathToFileURL(path.resolve(file)).href;
const browser = await chromium.launch();
const report = { errors: [], checks: {} };

async function open(viewport) {
  const page = await browser.newPage({ viewport });
  page.on("console", (m) => { if (m.type() === "error") report.errors.push(`${viewport.width}: ${m.text()}`); });
  page.on("pageerror", (e) => report.errors.push(`${viewport.width}: ${e}`));
  await page.goto(url, { waitUntil: "load" });
  return page;
}

const page = await open({ width: 1366, height: 768 });
report.checks.overflow_1366 = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
report.checks.layout = await page.evaluate(() => {
  const svg = document.querySelector("#graph svg");
  const vb = svg.viewBox.baseVal;
  const out = { textOverflow: [], nodeOverlap: [], outOfView: [] };
  const nodes = [...svg.querySelectorAll(".node")];
  const rects = nodes.map((g) => { const b = g.querySelector(".box").getBBox(); return { id: g.dataset.id, ...{ x: b.x, y: b.y, w: b.width, h: b.height } }; });
  nodes.forEach((g, i) => {
    const box = rects[i];
    const t = g.querySelector(".t").getBBox(), s = g.querySelector(".s").getBBox(), mb = g.querySelector(".mb").getBBox(), mt = g.querySelector(".mt").getBBox();
    if (t.x + t.width > mb.x - 4) out.textOverflow.push(`${box.id} 제목이 M배지 침범 (${(t.x + t.width - mb.x).toFixed(1)}px)`);
    if (s.x + s.width > box.x + box.w - 6) out.textOverflow.push(`${box.id} 부제 넘침`);
    if (t.y < box.y || s.y + s.height > box.y + box.h) out.textOverflow.push(`${box.id} 세로 넘침`);
    if (mt.x < mb.x || mt.x + mt.width > mb.x + mb.width) out.textOverflow.push(`${box.id} M배지 글자 넘침`);
    if (box.x < vb.x || box.y < vb.y || box.x + box.w > vb.x + vb.width || box.y + box.h > vb.y + vb.height) out.outOfView.push(box.id);
  });
  for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
    const a = rects[i], b = rects[j];
    if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) out.nodeOverlap.push(`${a.id}/${b.id}`);
  }
  const heads = [...svg.querySelectorAll(".lanehead, .bandhead")].map((t) => t.getBBox());
  out.headsInView = heads.every((h) => h.x >= 0 && h.x + h.width <= vb.width && h.y >= 0);
  return out;
});
await page.screenshot({ path: `${outDir}/onto_map_1366.png`, fullPage: true });

// 노드마다 선택 → 관계 라벨 겹침·노드 침범 측정
report.checks.labels = await page.evaluate(() => {
  const res = [];
  const svg = document.querySelector("#graph svg");
  const boxes = [...svg.querySelectorAll(".node .box")].map((r) => r.getBBox());
  for (const g of svg.querySelectorAll(".node")) {
    g.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const labs = [...svg.querySelectorAll(".elabel rect")].map((r) => r.getBBox());
    let overlap = 0, onNode = 0;
    for (let i = 0; i < labs.length; i++) {
      for (let j = i + 1; j < labs.length; j++) {
        const a = labs[i], b = labs[j];
        if (a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height) overlap++;
      }
      const a = labs[i];
      if (boxes.some((b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height)) onNode++;
    }
    if (overlap || onNode) res.push({ node: g.dataset.id, labels: labs.length, overlap, onNode });
  }
  return res;
});
// 상품 노드 선택 상태 캡처 + 드로어
await page.click('.node[data-id="product"]');
await page.waitForTimeout(350);
report.checks.drawerOpen = await page.evaluate(() => document.getElementById("drawer").classList.contains("open"));
await page.screenshot({ path: `${outDir}/onto_selected_product.png` });
await page.keyboard.press("Escape");
// 색 기준 전환
for (const m of ["input", "state", "lane", "stage"]) await page.click(`.seg button[data-mode="${m}"]`);
await page.click('.seg button[data-mode="input"]');
await page.screenshot({ path: `${outDir}/onto_mode_input.png` });
await page.click('.seg button[data-mode="stage"]');
// 탭
await page.click("#t-auto");
await page.screenshot({ path: `${outDir}/onto_auto.png`, fullPage: true });
await page.click("#t-dec");
await page.screenshot({ path: `${outDir}/onto_decisions.png`, fullPage: true });
await page.click('[data-decnodes]');
report.checks.decHighlight = await page.evaluate(() => document.querySelectorAll(".node.sel").length);
await page.click("#t-rel");
report.checks.relRows = await page.evaluate(() => document.querySelectorAll("#relations tbody tr").length);
// 인쇄
await page.emulateMedia({ media: "print" });
await page.screenshot({ path: `${outDir}/onto_print.png`, fullPage: true });
await page.emulateMedia({ media: "screen" });

const m = await open({ width: 390, height: 844 });
report.checks.overflow_390 = await m.evaluate(() => document.documentElement.scrollWidth - innerWidth);
await m.screenshot({ path: `${outDir}/onto_390.png`, fullPage: true });
await m.click("#t-auto");
report.checks.overflow_390_auto = await m.evaluate(() => document.documentElement.scrollWidth - innerWidth);
await m.click("#t-dec");
report.checks.overflow_390_dec = await m.evaluate(() => document.documentElement.scrollWidth - innerWidth);
await m.screenshot({ path: `${outDir}/onto_390_dec.png`, fullPage: true });
await browser.close();
console.log(JSON.stringify(report, null, 1));
const L = report.checks.layout;
const bad = report.errors.length || L.textOverflow.length || L.nodeOverlap.length || L.outOfView.length || !L.headsInView ||
  report.checks.overflow_1366 > 0 || report.checks.overflow_390 > 0 || report.checks.overflow_390_auto > 0 ||
  report.checks.overflow_390_dec > 0 || !report.checks.drawerOpen;
process.exit(bad ? 1 : 0);
