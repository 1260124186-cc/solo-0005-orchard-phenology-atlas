import { beforeEach, describe, expect, it } from "vitest";
import ObservationView from "../views/ObservationView.vue";
import { mount, flushPromises } from "@vue/test-utils";
import { useWorkspace } from "../app/workspace";
import { FakeStore, installFakeServer } from "../testing/fakeServer";
import { chooseOption, settle } from "../testing/mount";

const REQUIRED_STAGES = ["bud_burst", "full_bloom", "fruit_set", "harvest"];
const REQUIRED_DATES: Record<string, string> = {
  bud_burst: "2026-03-14",
  full_bloom: "2026-04-06",
  fruit_set: "2026-04-24",
  harvest: "2026-09-08",
};

async function seedAndSelect(store: FakeStore, code = "OR-7001") {
  const { plot, tree } = store.seedConfirmedPlot(code);
  store.seedOpenObservation(tree);
  const workspace = useWorkspace();
  await workspace.refreshPlots();
  await workspace.refreshObservations();
  await workspace.loadPlot(plot.id);
  workspace.selectObservation(
    workspace.state.observations[workspace.state.observations.length - 1].id,
  );
  return { plot, tree };
}

describe("ObservationView 阶段进度", () => {
  let store: FakeStore;

  beforeEach(async () => {
    document.body.innerHTML = "";
    store = new FakeStore();
    installFakeServer(store);
  });

  it("进度只统计四个必需阶段，从 0% 到 100%，并在页面真实渲染", async () => {
    await seedAndSelect(store);
    const wrapper = mount(ObservationView, { attachTo: document.body });
    await settle(wrapper);
    expect(wrapper.text()).toContain("0%");

    // 依次通过真实页面表单补录四个必需阶段。
    for (const stage of REQUIRED_STAGES) {
      await chooseOption('[data-check="stage-key"]', stage);
      await wrapper
        .get<HTMLInputElement>('[data-check="stage-date"]')
        .setValue(REQUIRED_DATES[stage]);
      await wrapper.get('[data-check="add-stage"]').trigger("submit");
      await settle(wrapper);
    }
    expect(wrapper.text()).toContain("100%");
    // 四个必需阶段轨道节点全部是已完成状态。
    for (const stage of REQUIRED_STAGES) {
      expect(wrapper.find(`[data-stage="${stage}"]`).classes()).toContain(
        "is-done",
      );
    }
  });

  it("可选阶段（芽膨大）不提升必需阶段进度，但轨道仍显示已记录", async () => {
    await seedAndSelect(store, "OR-7002");
    const wrapper = mount(ObservationView, { attachTo: document.body });
    await settle(wrapper);

    await chooseOption('[data-check="stage-key"]', "bud_swell");
    await wrapper
      .get<HTMLInputElement>('[data-check="stage-date"]')
      .setValue("2026-03-01");
    await wrapper.get('[data-check="add-stage"]').trigger("submit");
    await settle(wrapper);

    expect(wrapper.text()).toContain("0%");
    expect(wrapper.find('[data-stage="bud_swell"]').classes()).toContain(
      "is-done",
    );
    // 萌芽期仍是“缺失的必需阶段”状态。
    expect(wrapper.find('[data-stage="bud_burst"]').classes()).toContain(
      "is-missing-required",
    );
  });

  it("必需阶段齐全后完成季节志，页面切换为冻结态且表单消失", async () => {
    await seedAndSelect(store, "OR-7003");
    const wrapper = mount(ObservationView, { attachTo: document.body });
    await settle(wrapper);
    for (const stage of REQUIRED_STAGES) {
      await chooseOption('[data-check="stage-key"]', stage);
      await wrapper
        .get<HTMLInputElement>('[data-check="stage-date"]')
        .setValue(REQUIRED_DATES[stage]);
      await wrapper.get('[data-check="add-stage"]').trigger("submit");
      await settle(wrapper);
    }
    await wrapper.get('[data-check="complete-season"]').trigger("click");
    await settle(wrapper);
    await flushPromises();

    expect(wrapper.get('[data-check="season-status"]').text()).toContain(
      "已完成",
    );
    expect(wrapper.find('[data-check="add-stage"]').exists()).toBe(false);
    expect(wrapper.find('[data-check="remove-stage"]').exists()).toBe(false);
  });
});
