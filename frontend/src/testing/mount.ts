import { nextTick } from "vue";
import { mount, flushPromises, VueWrapper } from "@vue/test-utils";
import App from "../App.vue";
import { useWorkspace } from "../app/workspace";
/**
 * 挂载完整 App（真实视图 + 真实 workspace + 经 fetch 的假后端），
 * 而不是直接调用纯函数，保证测试能发现组件接线层的回归。
 */
export async function mountApp(): Promise<VueWrapper<any>> {
  const wrapper = mount(App, { attachTo: document.body });
  await flushPromises();
  await nextTick();
  return wrapper;
}

export async function gotoWorkspace(
  wrapper: VueWrapper<any>,
  target: "catalog" | "observation" | "comparison" | "brief",
): Promise<void> {
  await wrapper.get(`[data-check="nav-${target}"]`).trigger("click");
  await flushPromises();
  await nextTick();
}

/**
 * 操作页面上的自定义 ChoiceField：打开触发器，再点击菜单项。
 */
export async function chooseOption(
  triggerSelector: string,
  value: string,
): Promise<void> {
  const trigger = document.querySelector<HTMLButtonElement>(triggerSelector);
  if (!trigger) throw new Error(`找不到选择器：${triggerSelector}`);
  trigger.click();
  await nextTick();
  const option = document.querySelector<HTMLButtonElement>(
    `[data-choice-value="${value}"]`,
  );
  if (!option) throw new Error(`找不到选项：${value}`);
  expect(option.disabled).toBe(false);
  option.click();
  await nextTick();
}

export function errorNotices(wrapper: VueWrapper<any>): string[] {
  const workspace = useWorkspace();
  return workspace.state.notices
    .filter((notice) => notice.tone === "error")
    .map((notice) => notice.message);
}

export async function settle(wrapper: VueWrapper<any>): Promise<void> {
  void wrapper;
  await flushPromises();
  await nextTick();
  await flushPromises();
}
