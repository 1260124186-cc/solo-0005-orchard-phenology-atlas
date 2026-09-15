import { describe, expect, it, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";
import ObservationStageForm from "../components/ObservationStageForm.vue";
import type { StageEntry } from "../domain/types";

function mountForm(entries: readonly StageEntry[] = []) {
  return mount(ObservationStageForm, {
    props: { observation: { entries } },
    attachTo: document.body,
  });
}

function entry(stage: string, observedOn: string): StageEntry {
  return {
    id: `entry-${stage}`,
    stage,
    observed_on: observedOn,
    confidence: 4,
    note: "",
    created_at: "2026-01-01T00:00:00+00:00",
  };
}

async function chooseStage(wrapper: ReturnType<typeof mountForm>, stage: string) {
  await wrapper.get('[data-check="stage-key"]').trigger("click");
  const option = document.querySelector<HTMLButtonElement>(
    `[data-choice-value="${stage}"]`,
  );
  expect(option).not.toBeNull();
  option?.click();
  await wrapper.vm.$nextTick();
}

describe("ObservationStageForm 日期精度与顺序反馈", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("补录阶段时发出恰好十位 YYYY-MM-DD 的日期，不携带时分秒", async () => {
    const wrapper = mountForm();
    await chooseStage(wrapper, "bud_burst");
    await wrapper
      .get<HTMLInputElement>('[data-check="stage-date"]')
      .setValue("2026-03-14");
    await wrapper.get('[data-check="add-stage"]').trigger("submit");

    const events = wrapper.emitted("add");
    expect(events).toHaveLength(1);
    const payload = events?.[0]?.[0] as Record<string, unknown>;
    expect(payload.stage).toBe("bud_burst");
    expect(String(payload.observed_on)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(String(payload.observed_on)).toHaveLength(10);
    expect(payload.observed_on).toBe("2026-03-14");
  });

  it("后一阶段日期早于前序阶段时给出顺序错误且不发出 add", async () => {
    // 已有萌芽期 3 月 14 日；盛花期却填 3 月 1 日：日期倒退必须在前端拦截。
    const wrapper = mountForm([entry("bud_burst", "2026-03-14")]);
    await chooseStage(wrapper, "full_bloom");
    await wrapper
      .get<HTMLInputElement>('[data-check="stage-date"]')
      .setValue("2026-03-01");
    await wrapper.get('[data-check="add-stage"]').trigger("submit");

    expect(wrapper.emitted("add")).toBeUndefined();
    expect(wrapper.text()).toContain("不能早于");
    expect(wrapper.text()).toContain("萌芽期");
  });

  it("日期为空时提示选择观察日期而不是放行", async () => {
    const wrapper = mountForm();
    await chooseStage(wrapper, "bud_burst");
    await wrapper.get<HTMLInputElement>('[data-check="stage-date"]').setValue("");
    await wrapper.get('[data-check="add-stage"]').trigger("submit");
    expect(wrapper.emitted("add")).toBeUndefined();
    expect(wrapper.text()).toContain("请选择观察日期");
  });

  it("已登记阶段在真实选择菜单中被禁用，防止重复补录", async () => {
    const wrapper = mountForm([entry("bud_burst", "2026-03-14")]);
    await wrapper.get('[data-check="stage-key"]').trigger("click");
    const used = document.querySelector<HTMLButtonElement>(
      '[data-choice-value="bud_burst"]',
    );
    const unused = document.querySelector<HTMLButtonElement>(
      '[data-choice-value="full_bloom"]',
    );
    expect(used?.disabled).toBe(true);
    expect(unused?.disabled).toBe(false);
  });
});
