#!/usr/bin/env node
/** 单条浏览器工作流检查：真实后端 + 真实 Vite 页面 + Playwright。 */

import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "playwright";
import {
  API_HOST,
  ROOT,
  UI_HOST,
  assertPortFree,
  createGuard,
  hasFlag,
  makeLogDir,
  makeRuntimeDir,
  removeDirQuietly,
  resolvePort,
  resolveTimeout,
  startProcess,
  valueAfter,
  waitForUrl,
} from "./lib/check_runtime.mjs";

const workflow = valueAfter("--workflow");
const VALID_WORKFLOWS = new Set(["catalog", "observe", "compare"]);

if (!VALID_WORKFLOWS.has(workflow)) {
  console.error(
    "用法：node scripts/workflow_check.mjs --workflow catalog|observe|compare " +
      "[--api-port 8765] [--ui-port 4317] [--timeout-ms 180000] " +
      "[--log-dir <目录>] [--keep-logs]",
  );
  process.exit(2);
}

const API_PORT = resolvePort("--api-port", "ORCHARD_CHECK_API_PORT", 8765);
const UI_PORT = resolvePort("--ui-port", "ORCHARD_CHECK_UI_PORT", 4317);
const TIMEOUT_MS = resolveTimeout("--timeout-ms", "ORCHARD_CHECK_TIMEOUT_MS", 180_000);
const KEEP_LOGS = hasFlag("--keep-logs");
const API_ORIGIN = `http://${API_HOST}:${API_PORT}`;
const UI_ORIGIN = `http://${UI_HOST}:${UI_PORT}`;

const logDir = valueAfter("--log-dir") || makeLogDir(`workflow-${workflow}`);
mkdirSync(logDir, { recursive: true });
const runtimeDir = makeRuntimeDir();
const guard = createGuard({
  timeoutMs: TIMEOUT_MS,
  scope: `workflow:${workflow}`,
  logDir,
});
guard.state.dirs.push(runtimeDir);

let failed = null;

try {
  // 端口预检：被占用时立即失败并给出定位信息，不干扰占用方进程。
  await assertPortFree(API_PORT, API_HOST);
  await assertPortFree(UI_PORT, UI_HOST);

  const backend = startProcess(
    "python3",
    [
      "scripts/run_server.py",
      "--host",
      API_HOST,
      "--port",
      String(API_PORT),
      "--data-dir",
      runtimeDir,
    ],
    { logPath: join(logDir, "backend.log"), label: "backend" },
  );
  guard.state.processes.push(backend);
  await waitForUrl(`${API_ORIGIN}/api/health`, 20_000, () => backend.output);

  const frontend = startProcess(
    process.execPath,
    [
      join(ROOT, "node_modules", "vite", "bin", "vite.js"),
      "--host",
      UI_HOST,
      "--port",
      String(UI_PORT),
      "--strictPort",
    ],
    {
      logPath: join(logDir, "frontend.log"),
      label: "frontend",
      env: { ORCHARD_ATLAS_PORT: String(API_PORT) },
    },
  );
  guard.state.processes.push(frontend);
  await waitForUrl(`${UI_ORIGIN}/`, 20_000, () => frontend.output);

  // handleSIG*置 false：信号处理由本脚本的 guard 独占，
  // 避免 Playwright 默认处理器抢先 process.exit 导致子进程泄漏。
  const browser = await chromium.launch({
    headless: true,
    handleSIGINT: false,
    handleSIGTERM: false,
    handleSIGHUP: false,
  });
  guard.state.browsers.push(browser);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 980 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  await page.goto(UI_ORIGIN, { waitUntil: "networkidle" });
  await page.locator('[data-check="nav-catalog"]').waitFor();

  if (workflow === "catalog") {
    await checkCatalog(page);
  } else if (workflow === "observe") {
    await checkObservation(page);
  } else {
    await checkComparison(page);
  }

  console.log(`✅ ${workflow} 浏览器工作流检查通过`);
} catch (error) {
  failed = error;
  console.error(`❌ ${workflow} 浏览器工作流检查失败`);
  console.error(error instanceof Error ? error.stack : String(error));
  // 端口占用使用专属退出码，便于调用方区分环境问题与断言失败
  process.exitCode = error instanceof Error && error.message.includes("已被占用") ? 3 : 1;
} finally {
  await guard.cleanup();
  if (guard.state.watchdog) clearTimeout(guard.state.watchdog);
  if (failed) {
    // 失败一律保留日志目录，便于定位
    console.error(`📁 失败日志保留在 ${logDir}`);
  } else if (!KEEP_LOGS) {
    removeDirQuietly(logDir);
  } else {
    console.log(`📁 检查日志保留在 ${logDir}`);
  }
}

async function checkCatalog(page) {
  await page.locator('[data-check="nav-catalog"]').click();
  await page.locator('[data-check="plot-code"]').fill("OR-2101");
  await page.locator('[data-check="plot-name"]').fill("北岭老梨园");
  await page.locator('[data-check="plot-locality"]').fill("河湾村北岭东侧");
  await page.locator('[data-check="plot-focus"]').fill("黄皮秋梨");
  await page.locator('[data-check="plot-steward"]').fill("县农业志编研组");
  await page.locator('[data-check="plot-year"]').fill("2009");
  await page.locator('[data-check="plot-note"]').fill("保留传统梯田式栽植格局");
  await page.locator('[data-check="create-plot"]').click();
  await page.getByText("园区草稿已入档").waitFor();

  await page.locator('[data-check="tree-code"]').fill("OR-2101-T01");
  await page.locator('[data-check="tree-cultivar"]').fill("黄皮秋梨");
  await page.locator('[data-check="tree-rootstock"]').fill("杜梨");
  await page.locator('[data-check="tree-year"]').fill("2009");
  await page.locator('[data-check="create-tree"]').click();
  await page.getByText("植株已加入园区").waitFor();
  await page.locator('[data-check="tree-card"]').first().waitFor();

  await page.locator('[data-check="confirm-plot"]').click();
  await page.getByText("园区档案已确认并锁定").waitFor();
  const status = await page.locator('[data-check="plot-status"]').innerText();
  if (!status.includes("已确认")) {
    throw new Error("页面未显示园区已确认状态");
  }

  const plots = await api("/plots?q=OR-2101");
  const plot = plots.items.find((item) => item.code === "OR-2101");
  if (!plot || plot.status !== "confirmed" || plot.tree_count !== 1) {
    throw new Error("服务端园区确认结果不符合预期");
  }
  const trees = await api(`/trees?plot_id=${encodeURIComponent(plot.id)}`);
  if (trees.items.length !== 1 || trees.items[0].code !== "OR-2101-T01") {
    throw new Error("服务端植株目录与页面操作不一致");
  }
}

async function checkObservation(page) {
  const { plot, tree } = await seedCatalog("OR-2201", "东溪古梨园", "青玉梨");
  await page.reload({ waitUntil: "networkidle" });
  await page.locator('[data-check="nav-observation"]').click();
  await page.locator('[data-check="season-plot"]').click();
  await page.locator(`[data-choice-value="${plot.id}"]`).click();
  await page.locator('[data-check="season-tree"]').click();
  await page.locator(`[data-choice-value="${tree.id}"]`).click();
  await page.locator('[data-check="season-year"]').fill("2026");
  await page.locator('[data-check="season-observer"]').fill("周岚");
  await page.locator('[data-check="start-season"]').click();
  await page.getByText("季节志已建立，可以开始补录阶段").waitFor();

  const entries = [
    ["bud_burst", "2026-03-14"],
    ["full_bloom", "2026-04-06"],
    ["fruit_set", "2026-04-24"],
    ["harvest", "2026-09-08"],
  ];
  for (let index = 0; index < entries.length; index += 1) {
    await page.locator('[data-check="stage-key"]').click();
    await page.locator(`[data-choice-value="${entries[index][0]}"]`).click();
    await page.locator('[data-check="stage-date"]').fill(entries[index][1]);
    await page.locator('[data-check="stage-confidence"]').click();
    await page.locator('[data-choice-value="4"]').click();
    await page.locator('[data-check="add-stage"]').click();
    await page
      .locator('[data-check="stage-entry"]')
      .nth(index)
      .waitFor();
  }
  await page.locator('[data-check="complete-season"]').click();
  await page.getByText("季节志已完成并冻结").waitFor();
  const status = await page.locator('[data-check="season-status"]').innerText();
  if (!status.includes("已完成")) {
    throw new Error("页面未显示季节志完成状态");
  }

  const observations = await api(
    `/observations?tree_id=${encodeURIComponent(tree.id)}`,
  );
  const observation = observations.items[0];
  if (
    observation?.status !== "completed" ||
    observation.entries.length !== entries.length
  ) {
    throw new Error("服务端季节志与页面操作不一致");
  }
}

async function checkComparison(page) {
  const first = await seedCompletedSeason({
    plotCode: "OR-2301",
    plotName: "西坡梨园",
    cultivar: "秋白梨",
    treeCode: "OR-2301-T01",
    season: "2026",
    dates: ["2026-03-10", "2026-04-01", "2026-04-18", "2026-09-02"],
  });
  const second = await seedCompletedSeason({
    plotCode: "OR-2302",
    plotName: "南坳梨园",
    cultivar: "蜜香梨",
    treeCode: "OR-2302-T01",
    season: "2026",
    dates: ["2026-03-15", "2026-04-05", "2026-04-22", "2026-09-07"],
  });

  await page.reload({ waitUntil: "networkidle" });
  await page.locator('[data-check="nav-comparison"]').click();
  const leftLabel = await page
    .locator('[data-check="left-observation"]')
    .innerText();
  const rightLabel = await page
    .locator('[data-check="right-observation"]')
    .innerText();
  if (!leftLabel.trim() || !rightLabel.trim() || leftLabel === rightLabel) {
    throw new Error("页面未自动选择两份有效季节志");
  }
  await page.locator('[data-check="comparison-title"]').fill(
    "2026 年秋白梨与蜜香梨物候对齐",
  );
  await page.locator('[data-check="create-comparison"]').click();
  await page.getByText("对比图谱已生成并保存").waitFor();
  await page.locator('[data-check="comparison-result"]').waitFor();
  const offsetRows = page.locator('[data-check="offset-row"]');
  if ((await offsetRows.count()) !== 4) {
    throw new Error("页面未展示四个共同阶段的偏移");
  }
  const sentence = await page.locator('[data-check="comparison-sentence"]').innerText();
  if (!sentence.includes("共有 4 个阶段")) {
    throw new Error("页面比较摘要内容不完整");
  }

  const comparisons = await api("/comparisons");
  if (comparisons.items.length !== 1) {
    throw new Error("服务端未保存对比图谱");
  }
  if (comparisons.items[0].stage_offsets.length !== 4) {
    throw new Error("服务端对比阶段数不符合预期");
  }
}

async function seedCatalog(code, name, cultivar) {
  const plot = await api("/plots", "PUT", {
    code,
    name,
    locality: "山谷传统种植区",
    cultivar_focus: cultivar,
    steward: "物候档案组",
    planting_year: 2012,
    note: "用于浏览器工作流检查",
  });
  const tree = await api("/trees", "PUT", {
    plot_id: plot.id,
    code: `${code}-T01`,
    cultivar,
    rootstock: "杜梨",
    planting_year: 2012,
    status: "active",
    note: "",
  });
  const confirmed = await api(`/plots/${plot.id}/confirm`, "PUT", {
    revision: plot.revision,
  });
  return { plot: confirmed, tree };
}

async function seedCompletedSeason(config) {
  const { plot, tree } = await seedCatalog(
    config.plotCode,
    config.plotName,
    config.cultivar,
  );
  let observation = await api("/observations", "PUT", {
    tree_id: tree.id,
    season: config.season,
    observer: "对比检查组",
    note: "",
  });
  const stages = ["bud_burst", "full_bloom", "fruit_set", "harvest"];
  for (let index = 0; index < stages.length; index += 1) {
    observation = await api(
      `/observations/${observation.id}/stages`,
      "PUT",
      {
        stage: stages[index],
        observed_on: config.dates[index],
        confidence: 4,
        note: "",
        revision: observation.revision,
      },
    );
  }
  observation = await api(
    `/observations/${observation.id}/complete`,
    "PUT",
    { revision: observation.revision },
  );
  if (!plot || observation.status !== "completed") {
    throw new Error("准备比较数据失败");
  }
  return observation;
}

async function api(path, method = "GET", body) {
  const response = await fetch(`${API_ORIGIN}/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(
      `API ${method} ${path} 失败：${payload.error?.message ?? response.status}`,
    );
  }
  return payload;
}
