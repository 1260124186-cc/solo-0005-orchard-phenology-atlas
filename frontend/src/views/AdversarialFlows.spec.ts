/**
 * 三类对抗场景的前端集成验证。
 *
 * 这些用例挂载完整 App（视图 + workspace + 真实 api 客户端 + 假后端契约），
 * 因为冲突反馈 ToastStack 挂在 App 层，单独挂视图无法验证完整链路。
 *
 * A. 同一操作并发提交：重复点击/并发补录同一阶段，只有一次落库；
 * B. 第一次写入业务成功但后续关系检查失败：模拟服务端在成功建志后、
 *    补录阶段时拒绝（关系检查在服务端事务末尾执行），页面必须回到与
 *    服务端一致的状态，不能出现“页面有、库里无”的阶段；
 * C. 页面显示的最新版本与接口重新读取结果不一致：页面持有旧 revision，
 *    另一请求已推进修订号，提交必须收到 409，随后重新读取以服务端为准。
 */

import { beforeEach, describe, expect, it } from "vitest";
import App from "../App.vue";
import { useWorkspace } from "../app/workspace";
import { FakeStore, installFakeServer } from "../testing/fakeServer";
import { gotoWorkspace, mountApp, settle } from "../testing/mount";

const REQUIRED_DATES: Record<string, string> = {
  bud_burst: "2026-03-14",
  full_bloom: "2026-04-06",
  fruit_set: "2026-04-24",
  harvest: "2026-09-08",
};

async function seedObservation(store: FakeStore, code = "OR-7201", season = "2026") {
  const { plot, tree } = store.seedConfirmedPlot(code);
  store.seedOpenObservation(tree, season);
  return { plot, tree };
}

async function openFirstObservation() {
  const workspace = useWorkspace();
  await workspace.refreshPlots();
  await workspace.refreshObservations();
  const observation = workspace.state.observations[0];
  workspace.selectObservation(observation.id);
  return observation;
}

describe("对抗场景 A：同一操作并发提交", () => {
  let store: FakeStore;

  beforeEach(() => {
    document.body.innerHTML = "";
    store = new FakeStore();
    installFakeServer(store);
  });

  it("同一阶段补录被并发提交两次，只产生一条条目并给出冲突反馈", async () => {
    await seedObservation(store);
    const wrapper = await mountApp();
    await gotoWorkspace(wrapper, "observation");
    const observation = await openFirstObservation();
    await settle(wrapper);

    // 通过真实页面表单准备一份萌芽期补录。
    const stageTrigger = document.querySelector<HTMLButtonElement>(
      '[data-check="stage-key"]',
    );
    stageTrigger?.click();
    await settle(wrapper);
    document
      .querySelector<HTMLButtonElement>('[data-choice-value="bud_burst"]')
      ?.click();
    await settle(wrapper);
    await wrapper
      .get<HTMLInputElement>('[data-check="stage-date"]')
      .setValue("2026-03-14");

    // 截获表单的 add 事件处理：ObservationView.addStage 内部用 runAction
    // 包裹 workspace.addStage，因此两次并发点击都会走完整的错误反馈链路。
    const workspace = useWorkspace();
    const payload = {
      stage: "bud_burst",
      observed_on: "2026-03-14",
      confidence: 4,
      note: "",
    };
    const first = workspace.runAction(
      () => workspace.addStage(observation, payload),
      "物候阶段已补录",
    );
    const second = workspace.runAction(
      () => workspace.addStage(observation, payload),
      "物候阶段已补录",
    );
    await Promise.allSettled([first, second]);
    await settle(wrapper);

    // 关键事实断言：服务端只有一条萌芽期，页面也只渲染一行。
    const serverSide = [...store.observations.values()][0];
    expect(serverSide.entries).toHaveLength(1);
    expect(serverSide.entries[0].stage).toBe("bud_burst");
    expect(wrapper.findAll('[data-check="stage-entry"]')).toHaveLength(1);
    // 失败请求必须通过 ToastStack 给出冲突反馈（修订号或阶段重复）。
    const notices = workspace.state.notices
      .filter((notice) => notice.tone === "error")
      .map((notice) => notice.message)
      .join(" ");
    expect(notices).toMatch(/修订|重新读取|已经记录/);
    expect(document.body.textContent).toMatch(/修订|重新读取|已经记录/);
  });
});

describe("对抗场景 B：写入成功后后续关系检查失败", () => {
  let store: FakeStore;

  beforeEach(() => {
    document.body.innerHTML = "";
    store = new FakeStore();
  });

  it("建志成功后补录阶段被服务端关系检查回滚，页面与重新读取保持一致", async () => {
    await seedObservation(store, "OR-7211");
    // 钩子模拟：建志（PUT /observations）成功；第一次补录阶段时，
    // 服务端在事务末尾的关系检查中失败（500），该阶段必须整体回滚。
    let stageAttempt = 0;
    installFakeServer(store, {
      beforeWrite: ({ method, path }) => {
        if (method === "PUT" && /\/stages$/.test(path)) {
          stageAttempt += 1;
          if (stageAttempt === 1) {
            return {
              status: 500,
              body: {
                error: {
                  code: "state_relationships_invalid",
                  message: "事务会产生无效的对象关系",
                  details: {},
                },
              },
            };
          }
        }
      },
    });

    const wrapper = await mountApp();
    await gotoWorkspace(wrapper, "observation");
    const observation = await openFirstObservation();
    await settle(wrapper);

    const workspace = useWorkspace();
    await workspace.runAction(
      () =>
        workspace.addStage(observation, {
          stage: "bud_burst",
          observed_on: "2026-03-14",
          confidence: 4,
          note: "",
        }),
      "不应出现的成功提示",
    );
    await settle(wrapper);

    // 服务端：阶段没有落库（关系检查失败导致整笔回滚）。
    const serverSide = [...store.observations.values()][0];
    expect(serverSide.entries).toHaveLength(0);
    expect(serverSide.revision).toBe(1);

    // 页面：不能乐观地保留该阶段，必须与重新读取结果一致。
    expect(wrapper.findAll('[data-check="stage-entry"]')).toHaveLength(0);
    expect(document.body.textContent).toContain("对象关系");

    // 重新读取（刷新观察列表）后仍然没有该阶段，且可以重新补录成功。
    await workspace.refreshObservations();
    workspace.selectObservation(serverSide.id);
    await settle(wrapper);
    const reloaded = workspace.state.observations[0];
    expect(reloaded.entries).toHaveLength(0);
    expect(reloaded.revision).toBe(1);

    const retry = await workspace.runAction(
      () =>
        workspace.addStage(reloaded, {
          stage: "bud_burst",
          observed_on: "2026-03-14",
          confidence: 4,
          note: "",
        }),
      "物候阶段已补录",
    );
    await settle(wrapper);
    expect(retry).not.toBeNull();
    expect(serverSide.entries).toHaveLength(1);
  });
});

describe("对抗场景 C：页面版本与接口重新读取结果不一致", () => {
  let store: FakeStore;

  beforeEach(() => {
    document.body.innerHTML = "";
    store = new FakeStore();
    installFakeServer(store);
  });

  it("页面持旧 revision 提交补录收到 409，重新读取后以服务端新版本为准", async () => {
    await seedObservation(store, "OR-7221");
    const wrapper = await mountApp();
    await gotoWorkspace(wrapper, "observation");
    const observation = await openFirstObservation();
    await settle(wrapper);

    const workspace = useWorkspace();

    // 另一个标签页/请求先用当前修订号成功补录萌芽期，服务端修订号推进到 2。
    const concurrent = await workspace.addStage(observation, {
      stage: "bud_burst",
      observed_on: "2026-03-14",
      confidence: 4,
      note: "另一标签页补录",
    });
    expect(concurrent.revision).toBe(2);

    // 当前页面仍持有 revision=1 的旧视图，尝试补录盛花期：
    // 乐观并发必须返回 revision_conflict，旧页面不得覆盖新事实。
    const stale = await workspace.runAction(
      () =>
        workspace.addStage(observation, {
          stage: "full_bloom",
          observed_on: "2026-04-06",
          confidence: 4,
          note: "",
        }),
      "不应出现的成功提示",
    );
    await settle(wrapper);
    expect(stale).toBeNull();
    expect(document.body.textContent).toContain("已被其他请求修改");

    // 此时页面状态已经被并发结果刷新为 revision=2 且只有萌芽期。
    const serverSide = [...store.observations.values()][0];
    expect(serverSide.revision).toBe(2);
    expect(serverSide.entries.map((entry) => entry.stage)).toEqual(["bud_burst"]);

    // 模拟用户“重新读取”：刷新后页面与服务端完全一致，再用新修订号补录成功。
    await workspace.refreshObservations();
    workspace.selectObservation(serverSide.id);
    await settle(wrapper);
    const reloaded = workspace.state.observations.find(
      (item) => item.id === serverSide.id,
    )!;
    expect(reloaded.revision).toBe(2);
    expect(reloaded.entries.map((entry) => entry.stage)).toEqual(["bud_burst"]);

    const after = await workspace.addStage(reloaded, {
      stage: "full_bloom",
      observed_on: "2026-04-06",
      confidence: 4,
      note: "",
    });
    expect(after.revision).toBe(3);
    expect(
      [...store.observations.values()][0].entries.map((entry) => entry.stage),
    ).toEqual(["bud_burst", "full_bloom"]);
  });

  it("用四个必需阶段完成季节志后，旧页面再尝试补录会被冻结规则拒绝", async () => {
    await seedObservation(store, "OR-7222");
    const wrapper = await mountApp();
    await gotoWorkspace(wrapper, "observation");
    const observation = await openFirstObservation();
    await settle(wrapper);

    const workspace = useWorkspace();
    let current = observation;
    for (const [stage, date] of Object.entries(REQUIRED_DATES)) {
      current = await workspace.addStage(current, {
        stage,
        observed_on: date,
        confidence: 4,
        note: "",
      });
    }
    await workspace.completeObservation(current);
    await settle(wrapper);

    // 已完成（revision 已推进）。旧引用 current 之后，再拿完成前的页面尝试
    // 补录落叶期：不可编辑规则必须胜出，不产生新条目。
    const stale = await workspace.runAction(
      () =>
        workspace.addStage(current, {
          stage: "leaf_fall",
          observed_on: "2026-11-20",
          confidence: 4,
          note: "",
        }),
      "不应出现的成功提示",
    );
    await settle(wrapper);
    expect(stale).toBeNull();
    expect(document.body.textContent).toContain("不可修改");
    const serverSide = [...store.observations.values()][0];
    expect(serverSide.status).toBe("completed");
    expect(serverSide.entries).toHaveLength(4);
  });
});
