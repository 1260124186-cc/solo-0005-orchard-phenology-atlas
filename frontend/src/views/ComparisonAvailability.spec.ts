import { beforeEach, describe, expect, it } from "vitest";
import ComparisonView from "./ComparisonView.vue";
import { mount } from "@vue/test-utils";
import { useWorkspace } from "../app/workspace";
import { FakeStore, installFakeServer } from "../testing/fakeServer";
import { chooseOption, settle } from "../testing/mount";

const DATES_LEFT = {
  bud_burst: "2026-03-10",
  full_bloom: "2026-04-01",
  fruit_set: "2026-04-18",
  harvest: "2026-09-02",
};
const DATES_RIGHT = {
  bud_burst: "2026-03-15",
  full_bloom: "2026-04-05",
  fruit_set: "2026-04-22",
  harvest: "2026-09-07",
};

async function mountComparison(store: FakeStore) {
  const workspace = useWorkspace();
  await workspace.initialize();
  await workspace.refreshObservations();
  const wrapper = mount(ComparisonView, { attachTo: document.body });
  await settle(wrapper);
  return wrapper;
}

describe("ComparisonView 比较可用条件", () => {
  let store: FakeStore;

  beforeEach(() => {
    document.body.innerHTML = "";
    store = new FakeStore();
    installFakeServer(store);
  });

  it("两份同年已完成且有共同阶段时按钮可用，并生成四条确定性偏移", async () => {
    const first = store.seedConfirmedPlot("OR-7101");
    const second = store.seedConfirmedPlot("OR-7102");
    store.seedCompletedObservation(first.tree, "2026", DATES_LEFT);
    store.seedCompletedObservation(second.tree, "2026", DATES_RIGHT);

    const wrapper = await mountComparison(store);
    const button = wrapper.get<HTMLButtonElement>(
      '[data-check="create-comparison"]',
    );
    expect(button.attributes("disabled")).toBeUndefined();

    await button.trigger("submit");
    await settle(wrapper);

    const rows = wrapper.findAll('[data-check="offset-row"]');
    expect(rows).toHaveLength(4);
    expect(wrapper.get('[data-check="comparison-sentence"]').text()).toContain(
      "共有 4 个阶段",
    );
    // 每行结构：阶段名 / 左侧日期 / 右侧日期 / 相对偏移 / 置信差。
    const offsets = rows.map((row) =>
      row.findAll("span")[2]?.text().trim(),
    );
    // 右侧减左侧：+5、+4、+4、+5 天。
    expect(offsets).toEqual(["晚 5 天", "晚 4 天", "晚 4 天", "晚 5 天"]);
  });

  it("年份不同的两份季节志：按钮禁用并显示年份提示", async () => {
    const first = store.seedConfirmedPlot("OR-7103");
    const second = store.seedConfirmedPlot("OR-7104");
    store.seedCompletedObservation(first.tree, "2025", DATES_LEFT);
    store.seedCompletedObservation(second.tree, "2026", DATES_RIGHT);

    const wrapper = await mountComparison(store);
    expect(
      wrapper.get<HTMLButtonElement>('[data-check="create-comparison"]').attributes(
        "disabled",
      ),
    ).toBeDefined();
    expect(wrapper.text()).toContain("年份不同");
  });

  it("两侧无共同阶段：按钮禁用并显示无共同阶段提示", async () => {
    const first = store.seedConfirmedPlot("OR-7105");
    const second = store.seedConfirmedPlot("OR-7106");
    const left = store.seedCompletedObservation(first.tree, "2026", DATES_LEFT);
    // 右侧覆盖为完全不相交的可选阶段（通过存储层直接构造，模拟迁移入档的
    // 合法完成季节志）。
    const right = store.seedCompletedObservation(second.tree, "2026", DATES_RIGHT);
    right.entries = [
      {
        id: "e1",
        stage: "bud_swell",
        observed_on: "2026-03-01",
        confidence: 4,
        note: "",
        created_at: "2026-01-01T00:00:00+00:00",
      },
      {
        id: "e2",
        stage: "leaf_fall",
        observed_on: "2026-11-20",
        confidence: 4,
        note: "",
        created_at: "2026-01-01T00:00:00+00:00",
      },
    ];
    void left;

    const wrapper = await mountComparison(store);
    expect(
      wrapper.get<HTMLButtonElement>('[data-check="create-comparison"]').attributes(
        "disabled",
      ),
    ).toBeDefined();
    expect(wrapper.text()).toContain("没有共同阶段");
  });

  it("少于两份已完成季节志时自动选择不成立，按钮保持禁用", async () => {
    const only = store.seedConfirmedPlot("OR-7107");
    store.seedCompletedObservation(only.tree, "2026", DATES_LEFT);
    const wrapper = await mountComparison(store);
    expect(
      wrapper.get<HTMLButtonElement>('[data-check="create-comparison"]').attributes(
        "disabled",
      ),
    ).toBeDefined();
  });

  it("服务端拒绝（无共同阶段 412）时页面显示冲突反馈且不出现结果区", async () => {
    const first = store.seedConfirmedPlot("OR-7108");
    const second = store.seedConfirmedPlot("OR-7109");
    store.seedCompletedObservation(first.tree, "2026", DATES_LEFT);
    store.seedCompletedObservation(second.tree, "2026", DATES_RIGHT);

    // 前端可用性判断通过后，服务端仍可能在提交点拒绝（例如共同阶段被另一
    // 请求移除）。用可变开关在提交瞬间返回 412，验证冲突反馈而非静默成功。
    let rejectComparison = false;
    installFakeServer(store, {
      beforeWrite: ({ method, path }) => {
        if (rejectComparison && method === "PUT" && path === "/comparisons") {
          return {
            status: 412,
            body: {
              error: {
                code: "no_common_stage",
                message: "两份季节志没有可比较的共同阶段",
                details: {},
              },
            },
          };
        }
      },
    });

    const wrapper = await mountComparison(store);
    rejectComparison = true;
    await wrapper.get('[data-check="create-comparison"]').trigger("submit");
    await settle(wrapper);

    expect(wrapper.find('[data-check="comparison-result"]').exists()).toBe(false);
    // 冲突反馈通过全局 ToastStack 呈现（挂在 App 层），这里直接核对
    // workspace 中产生的错误通知，以及比较结果未进入本地状态。
    const workspace = useWorkspace();
    const messages = workspace.state.notices.map((notice) => notice.message);
    expect(messages.join(" ")).toContain("没有可比较的共同阶段");
    expect(workspace.state.comparisons).toHaveLength(0);
  });
});
