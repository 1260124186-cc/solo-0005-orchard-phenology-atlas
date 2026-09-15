/**
 * 组件测试共享的内存“假后端”。
 *
 * 它不是纯函数测试夹具：fetch 被整体替换后，组件经由 services/api.ts 的
 * 真实 HTTP 客户端发起请求，假后端按后端真实契约返回：
 *
 * - 成功返回资源对象 / { items }；
 * - 失败返回 { error: { code, message, details } } 与真实状态码；
 * - PATCH/PUT/DELETE 走 revision 乐观并发控制，旧修订号返回 409；
 * - 季节志阶段顺序、必需阶段、完成后不可编辑等规则与后端一致。
 *
 * 这样可以在不启动浏览器的情况下，对“真实组件 + 真实客户端 + 类服务端契约”
 * 的整条链路做回归验证。
 */

export interface FakeTree {
  id: string;
  plot_id: string;
  code: string;
  cultivar: string;
  rootstock: string;
  planting_year: number;
  status: "active" | "retired" | "lost";
  note: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface FakeStageEntry {
  id: string;
  stage: string;
  observed_on: string;
  confidence: number;
  note: string;
  created_at: string;
}

export interface FakeObservation {
  id: string;
  tree_id: string;
  plot_id: string;
  tree_code: string;
  cultivar: string;
  season: string;
  observer: string;
  note: string;
  status: "open" | "completed";
  revision: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  entries: FakeStageEntry[];
}

export interface FakePlot {
  id: string;
  code: string;
  name: string;
  locality: string;
  cultivar_focus: string;
  steward: string;
  planting_year: number;
  note: string;
  status: "draft" | "confirmed";
  revision: number;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
}

interface StoredComparison {
  id: string;
  title: string;
  season: string;
  left_observation_id: string;
  right_observation_id: string;
  left_label: string;
  right_label: string;
  stage_offsets: Array<{
    stage: string;
    label: string;
    rank: number;
    left_date: string;
    right_date: string;
    offset_days: number;
    confidence_gap: number;
  }>;
  summary: Record<string, unknown> & { sentence: string; common_stage_count: number };
  created_at: string;
}

const STAGE_RANK: Record<string, number> = {
  bud_swell: 10,
  bud_burst: 20,
  first_bloom: 30,
  full_bloom: 40,
  petal_fall: 50,
  fruit_set: 60,
  fruit_growth: 70,
  harvest: 80,
  leaf_fall: 90,
};
const STAGE_LABEL: Record<string, string> = {
  bud_swell: "芽膨大期",
  bud_burst: "萌芽期",
  first_bloom: "初花期",
  full_bloom: "盛花期",
  petal_fall: "落瓣期",
  fruit_set: "坐果期",
  fruit_growth: "果实膨大期",
  harvest: "采收期",
  leaf_fall: "落叶期",
};
const REQUIRED = ["bud_burst", "full_bloom", "fruit_set", "harvest"];
const NOW = "2026-09-15T08:00:00+00:00";

let sequence = 0;
function nextId(prefix: string): string {
  sequence += 1;
  return `${prefix}_${String(sequence).padStart(8, "0")}`;
}

function observationSummary(observation: FakeObservation, tree: FakeTree) {
  const entries = [...observation.entries].sort(
    (left, right) =>
      STAGE_RANK[left.stage] - STAGE_RANK[right.stage] ||
      left.observed_on.localeCompare(right.observed_on),
  );
  return {
    ...observation,
    tree_code: tree.code,
    cultivar: tree.cultivar,
    entries,
    stage_count: entries.length,
    entry_map: Object.fromEntries(
      entries.map((entry) => [
        entry.stage,
        {
          observed_on: entry.observed_on,
          confidence: entry.confidence,
          note: entry.note,
        },
      ]),
    ),
  };
}

export interface FakeServerOptions {
  /**
   * 每次写请求落库前调用；返回一个错误即可模拟“接口重新读取与页面不一致”
   * 之外的服务端竞态，或直接改写 store 制造页面陈旧。
   */
  beforeWrite?: (context: {
    method: string;
    path: string;
    body: any;
    store: FakeStore;
  }) => FakeResponse | void;
}

interface FakeResponse {
  status: number;
  body: unknown;
}

export class FakeStore {
  plots = new Map<string, FakePlot>();
  trees = new Map<string, FakeTree>();
  observations = new Map<string, FakeObservation>();
  comparisons = new Map<string, StoredComparison>();
  idempotency = new Map<string, { hash: string; response: unknown }>();

  reset(): void {
    this.plots.clear();
    this.trees.clear();
    this.observations.clear();
    this.comparisons.clear();
    this.idempotency.clear();
    sequence = 0;
  }

  seedConfirmedPlot(code: string, treeSuffix = "T01"): { plot: FakePlot; tree: FakeTree } {
    const plot: FakePlot = {
      id: nextId("plot"),
      code,
      name: `测试园区 ${code}`,
      locality: "河湾村",
      cultivar_focus: "黄皮秋梨",
      steward: "档案组",
      planting_year: 2010,
      note: "",
      status: "confirmed",
      revision: 2,
      created_at: NOW,
      updated_at: NOW,
      confirmed_at: NOW,
    };
    const tree: FakeTree = {
      id: nextId("tree"),
      plot_id: plot.id,
      code: `${code}-${treeSuffix}`,
      cultivar: "黄皮秋梨",
      rootstock: "杜梨",
      planting_year: 2012,
      status: "active",
      note: "",
      revision: 1,
      created_at: NOW,
      updated_at: NOW,
    };
    this.plots.set(plot.id, plot);
    this.trees.set(tree.id, tree);
    return { plot, tree };
  }

  seedOpenObservation(tree: FakeTree, season = "2026"): FakeObservation {
    const observation: FakeObservation = {
      id: nextId("season"),
      tree_id: tree.id,
      plot_id: tree.plot_id,
      tree_code: tree.code,
      cultivar: tree.cultivar,
      season,
      observer: "周岚",
      note: "",
      status: "open",
      revision: 1,
      created_at: NOW,
      updated_at: NOW,
      completed_at: null,
      entries: [],
    };
    this.observations.set(observation.id, observation);
    return observation;
  }

  seedCompletedObservation(
    tree: FakeTree,
    season: string,
    dates: Record<string, string>,
  ): FakeObservation {
    const observation = this.seedOpenObservation(tree, season);
    for (const [stage, observedOn] of Object.entries(dates)) {
      observation.entries.push({
        id: nextId("entry"),
        stage,
        observed_on: observedOn,
        confidence: 4,
        note: "",
        created_at: NOW,
      });
    }
    observation.status = "completed";
    observation.completed_at = NOW;
    observation.revision = observation.entries.length + 1;
    return observation;
  }
}

function error(
  status: number,
  code: string,
  message: string,
  details: Record<string, unknown> = {},
): FakeResponse {
  return { status, body: { error: { code, message, details } } };
}

function daysBetween(left: string, right: string): number {
  const leftDate = new Date(`${left}T00:00:00Z`).getTime();
  const rightDate = new Date(`${right}T00:00:00Z`).getTime();
  return Math.round((rightDate - leftDate) / 86_400_000);
}

export function installFakeServer(
  store: FakeStore,
  options: FakeServerOptions = {},
): void {
  const fetchImpl = vi.fn(async (input: any, init?: RequestInit) => {
    const rawUrl = String(typeof input === "string" ? input : input.url);
    const url = new URL(rawUrl, "http://local-app.test");
    const path = url.pathname.replace(/^\/api/, "");
    const method = String(init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : {};

    const hook = options.beforeWrite?.({ method, path, body, store });
    if (hook) return respond(hook);

    // 幂等键处理与后端一致：相同 actor+key 复用，同键不同体冲突。
    const headers = new Headers(init?.headers);
    const actor = headers.get("X-Actor-Id") || "local-admin";
    const idempotencyKey = headers.get("X-Idempotency-Key");
    const bodyHash = JSON.stringify(body);

    if (idempotencyKey && method !== "GET") {
      const idempotencyId = `${actor}:${idempotencyKey}`;
      const previous = store.idempotency.get(idempotencyId);
      if (previous && previous.hash !== bodyHash) {
        return respond(
          error(409, "idempotency_key_reused", "同一幂等键已用于不同请求"),
        );
      }
      if (previous) {
        return respond({ status: 200, body: previous.response });
      }
      const response = route(store, method, path, url.searchParams, body);
      if (response.status === 200) {
        store.idempotency.set(idempotencyId, {
          hash: bodyHash,
          response: response.body,
        });
      }
      return respond(response);
    }

    return respond(route(store, method, path, url.searchParams, body));
  });
  vi.stubGlobal("fetch", fetchImpl);
}

function respond(response: FakeResponse): Response {
  return new Response(JSON.stringify(response.body), {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}

function route(
  store: FakeStore,
  method: string,
  path: string,
  query: URLSearchParams,
  body: any,
): FakeResponse {
  if (method === "GET" && path === "/health") {
    return { status: 200, body: { status: "ok", service: "fake" } };
  }
  if (method === "GET" && path === "/plots") {
    const q = (query.get("q") || "").toLowerCase();
    const items = [...store.plots.values()]
      .filter((plot) => !q || `${plot.code} ${plot.name}`.toLowerCase().includes(q))
      .map((plot) => ({
        ...plot,
        tree_count: [...store.trees.values()].filter(
          (tree) => tree.plot_id === plot.id,
        ).length,
      }));
    return { status: 200, body: { items, total: items.length, state_revision: 1 } };
  }
  const plotMatch = path.match(/^\/plots\/([^/]+)$/);
  if (method === "GET" && plotMatch) {
    const plot = store.plots.get(plotMatch[1]);
    if (!plot) return error(404, "not_found", "未找到园区");
    const trees = [...store.trees.values()].filter(
      (tree) => tree.plot_id === plot.id,
    );
    return {
      status: 200,
      body: {
        ...plot,
        tree_count: trees.length,
        trees: trees.sort((left, right) => left.code.localeCompare(right.code)),
      },
    };
  }
  if (method === "PUT" && path === "/trees") {
    const plot = store.plots.get(body.plot_id);
    if (!plot) return error(404, "not_found", "未找到园区");
    if (plot.status !== "draft")
      return error(412, "plot_not_editable", "只能向草稿园区添加植株");
    if (
      [...store.trees.values()].some(
        (item) => item.plot_id === plot.id && item.code === body.code,
      )
    )
      // 与真实后端相同的稳定错误码（真实实现 F-001 的 500 已由后端测试记录）。
      return error(409, "tree_code_exists", "该园区内植株编号已存在");
    const record: FakeTree = {
      id: nextId("tree"),
      plot_id: plot.id,
      code: body.code,
      cultivar: body.cultivar,
      rootstock: body.rootstock ?? "未记录",
      planting_year: body.planting_year,
      status: "active",
      note: body.note ?? "",
      revision: 1,
      created_at: NOW,
      updated_at: NOW,
    };
    store.trees.set(record.id, record);
    return { status: 200, body: record };
  }
  const confirmMatch = path.match(/^\/plots\/([^/]+)\/confirm$/);
  if (method === "PUT" && confirmMatch) {
    const plot = store.plots.get(confirmMatch[1]);
    if (!plot) return error(404, "not_found", "未找到园区");
    if (plot.status === "confirmed")
      return error(412, "plot_already_confirmed", "园区已经确认");
    if (body.revision !== plot.revision)
      return error(
        409,
        "revision_conflict",
        "记录已被其他请求修改，请重新读取",
        { expected: body.revision, actual: plot.revision },
      );
    const hasActiveTree = [...store.trees.values()].some(
      (tree) => tree.plot_id === plot.id && tree.status === "active",
    );
    if (!hasActiveTree)
      return error(412, "plot_requires_tree", "确认前至少需要一株在册植株");
    plot.status = "confirmed";
    plot.confirmed_at = NOW;
    plot.revision += 1;
    plot.updated_at = NOW;
    return { status: 200, body: { ...plot } };
  }
  if (method === "GET" && path === "/observations") {
    const treeId = query.get("tree_id");
    const items = [...store.observations.values()]
      .filter((observation) => !treeId || observation.tree_id === treeId)
      .map((observation) =>
        observationSummary(
          observation,
          store.trees.get(observation.tree_id) as FakeTree,
        ),
      );
    return { status: 200, body: { items, total: items.length } };
  }
  const observationMatch = path.match(/^\/observations\/([^/]+)$/);
  if (method === "GET" && observationMatch) {
    const observation = store.observations.get(observationMatch[1]);
    if (!observation) return error(404, "not_found", "未找到季节志");
    return {
      status: 200,
      body: observationSummary(
        observation,
        store.trees.get(observation.tree_id) as FakeTree,
      ),
    };
  }
  if (method === "PUT" && path === "/observations") {
    const tree = store.trees.get(body.tree_id);
    if (!tree) return error(404, "not_found", "未找到植株");
    if (
      [...store.observations.values()].some(
        (item) => item.tree_id === body.tree_id && item.season === body.season,
      )
    )
      return error(409, "season_exists", "该植株在这一季节已有记录");
    const record = store.seedOpenObservation(tree, body.season);
    record.observer = body.observer;
    return {
      status: 200,
      body: observationSummary(record, tree),
    };
  }
  const stageMatch = path.match(/^\/observations\/([^/]+)\/stages$/);
  if (method === "PUT" && stageMatch) {
    const observation = store.observations.get(stageMatch[1]);
    if (!observation) return error(404, "not_found", "未找到季节志");
    if (observation.status === "completed")
      return error(412, "season_not_editable", "已完成的季节志不可修改");
    if (body.revision !== observation.revision)
      return error(
        409,
        "revision_conflict",
        "记录已被其他请求修改，请重新读取",
        { expected: body.revision, actual: observation.revision },
      );
    if (observation.entries.some((entry) => entry.stage === body.stage))
      return error(409, "stage_exists", "该阶段已经记录，请先移除原条目");
    const candidateEntries = [
      ...observation.entries,
      { stage: body.stage, observed_on: body.observed_on },
    ].sort(
      (left, right) =>
        STAGE_RANK[left.stage] - STAGE_RANK[right.stage] ||
        left.observed_on.localeCompare(right.observed_on),
    );
    for (let index = 1; index < candidateEntries.length; index += 1) {
      if (candidateEntries[index].observed_on < candidateEntries[index - 1].observed_on) {
        return error(
          422,
          "validation_error",
          "后一物候阶段的日期不能早于前一阶段",
          { field: "observed_on" },
        );
      }
    }
    observation.entries.push({
      id: nextId("entry"),
      stage: body.stage,
      observed_on: body.observed_on,
      confidence: body.confidence,
      note: body.note ?? "",
      created_at: NOW,
    });
    observation.revision += 1;
    observation.updated_at = NOW;
    return {
      status: 200,
      body: observationSummary(
        observation,
        store.trees.get(observation.tree_id) as FakeTree,
      ),
    };
  }
  const completeMatch = path.match(/^\/observations\/([^/]+)\/complete$/);
  if (method === "PUT" && completeMatch) {
    const observation = store.observations.get(completeMatch[1]);
    if (!observation) return error(404, "not_found", "未找到季节志");
    if (observation.status === "completed")
      return error(412, "season_not_editable", "已完成的季节志不可修改");
    if (body.revision !== observation.revision)
      return error(
        409,
        "revision_conflict",
        "记录已被其他请求修改，请重新读取",
        { expected: body.revision, actual: observation.revision },
      );
    const present = new Set(observation.entries.map((entry) => entry.stage));
    const missing = REQUIRED.filter((stage) => !present.has(stage));
    if (missing.length)
      return error(412, "required_stages_missing", "缺少完成季节志所需的阶段", {
        missing,
        labels: missing.map((stage) => STAGE_LABEL[stage]),
      });
    observation.status = "completed";
    observation.completed_at = NOW;
    observation.revision += 1;
    return {
      status: 200,
      body: observationSummary(
        observation,
        store.trees.get(observation.tree_id) as FakeTree,
      ),
    };
  }
  if (method === "GET" && path === "/comparisons") {
    return {
      status: 200,
      body: { items: [...store.comparisons.values()], total: store.comparisons.size },
    };
  }
  if (method === "PUT" && path === "/comparisons") {
    const left = store.observations.get(body.left_observation_id);
    const right = store.observations.get(body.right_observation_id);
    if (!left || !right) return error(404, "not_found", "未找到季节志");
    if (left.status !== "completed" || right.status !== "completed")
      return error(412, "season_not_completed", "只有已完成的季节志可以生成对比图谱");
    if (left.season !== right.season)
      return error(422, "validation_error", "两份季节志必须属于同一年份", {
        field: "season",
      });
    const leftEntries = new Map(left.entries.map((entry) => [entry.stage, entry]));
    const common = right.entries
      .filter((entry) => leftEntries.has(entry.stage))
      .sort((a, b) => STAGE_RANK[a.stage] - STAGE_RANK[b.stage]);
    if (common.length === 0)
      return error(412, "no_common_stage", "两份季节志没有可比较的共同阶段");
    const stageOffsets = common.map((rightEntry) => {
      const leftEntry = leftEntries.get(rightEntry.stage) as FakeStageEntry;
      return {
        stage: rightEntry.stage,
        label: STAGE_LABEL[rightEntry.stage],
        rank: STAGE_RANK[rightEntry.stage],
        left_date: leftEntry.observed_on,
        right_date: rightEntry.observed_on,
        offset_days: daysBetween(leftEntry.observed_on, rightEntry.observed_on),
        confidence_gap: Math.abs(
          leftEntry.confidence - rightEntry.confidence,
        ),
      };
    });
    const duplicate = [...store.comparisons.values()].find((item) => {
      const pair = new Set([item.left_observation_id, item.right_observation_id]);
      return (
        pair.has(body.left_observation_id) &&
        pair.has(body.right_observation_id)
      );
    });
    if (duplicate) return { status: 200, body: duplicate };
    const leftTree = store.trees.get(left.tree_id) as FakeTree;
    const rightTree = store.trees.get(right.tree_id) as FakeTree;
    const record: StoredComparison = {
      id: nextId("atlas"),
      title: body.title,
      season: left.season,
      left_observation_id: left.id,
      right_observation_id: right.id,
      left_label: `${leftTree.code} · ${leftTree.cultivar}`,
      right_label: `${rightTree.code} · ${rightTree.cultivar}`,
      stage_offsets: stageOffsets,
      summary: {
        title: body.title,
        common_stage_count: stageOffsets.length,
        average_offset_days: 0,
        minimum_offset_days: 0,
        maximum_offset_days: 0,
        earliest_stage: stageOffsets[0]?.label ?? "",
        latest_stage: stageOffsets[0]?.label ?? "",
        direction: "接近同步",
        stability: "阶段偏移较为集中",
        sentence: `${leftTree.code} 与 ${rightTree.code} 在 ${left.season} 年共有 ${stageOffsets.length} 个阶段可比较。`,
      },
      created_at: NOW,
    };
    store.comparisons.set(record.id, record);
    return { status: 200, body: record };
  }
  return error(404, "not_found", `接口不存在：${method} ${path}`);
}
