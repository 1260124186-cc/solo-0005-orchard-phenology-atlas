<script setup lang="ts">
import { computed, onMounted } from "vue";
import {
  BookOpenText,
  CalendarRange,
  GitCompareArrows,
  Leaf,
  LibraryBig,
  Sprout,
} from "@lucide/vue";
import ArchiveHeader from "./components/ArchiveHeader.vue";
import ToastStack from "./components/ToastStack.vue";
import BriefView from "./views/BriefView.vue";
import CatalogView from "./views/CatalogView.vue";
import ComparisonView from "./views/ComparisonView.vue";
import ObservationView from "./views/ObservationView.vue";
import { useWorkspace } from "./app/workspace";
import type { WorkspaceKey } from "./domain/types";

const workspace = useWorkspace();

const navigation = computed(() => [
  {
    key: "catalog" as WorkspaceKey,
    label: "园区档案",
    detail: `${workspace.state.plots.length} 个园区`,
    icon: LibraryBig,
  },
  {
    key: "observation" as WorkspaceKey,
    label: "物候观察",
    detail: `${workspace.state.observations.length} 份季节志`,
    icon: CalendarRange,
  },
  {
    key: "comparison" as WorkspaceKey,
    label: "图谱比较",
    detail: `${workspace.state.comparisons.length} 份对齐结果`,
    icon: GitCompareArrows,
  },
  {
    key: "brief" as WorkspaceKey,
    label: "编研简报",
    detail: "冻结档案摘编",
    icon: BookOpenText,
  },
]);

const workspaceTitle = computed(() => {
  const current = navigation.value.find(
    (item) => item.key === workspace.state.active,
  );
  return current?.label ?? "编研台";
});

onMounted(() => {
  void workspace.initialize();
});
</script>

<template>
  <div class="app-frame">
    <ArchiveHeader
      :online="workspace.state.backendOnline"
      :loading="workspace.state.loading"
    />

    <div class="workspace-shell">
      <aside class="workspace-rail" aria-label="编研工作区">
        <div class="rail-intro">
          <span class="eyebrow">本季编研</span>
          <strong>{{ workspaceTitle }}</strong>
          <p>从园区登记到阶段对齐，所有记录都保留在本地档案中。</p>
        </div>

        <nav class="workspace-nav">
          <button
            v-for="item in navigation"
            :key="item.key"
            type="button"
            class="workspace-nav__item"
            :class="{ 'is-active': workspace.state.active === item.key }"
            :data-check="`nav-${item.key}`"
            @click="workspace.setActiveWorkspace(item.key)"
          >
            <component :is="item.icon" :size="19" :stroke-width="1.8" />
            <span>
              <strong>{{ item.label }}</strong>
              <small>{{ item.detail }}</small>
            </span>
          </button>
        </nav>

        <div class="season-legend">
          <div class="season-legend__title">
            <Leaf :size="17" />
            <span>阶段基准</span>
          </div>
          <div class="season-legend__track" aria-hidden="true">
            <span />
            <i />
            <i />
            <i />
            <span />
          </div>
          <div class="season-legend__labels">
            <small>萌动</small>
            <small>花候</small>
            <small>坐果</small>
            <small>成熟</small>
          </div>
        </div>
      </aside>

      <main class="workspace-main">
        <header class="workspace-heading">
          <div>
            <span class="eyebrow">果园物候图谱</span>
            <h1>{{ workspaceTitle }}</h1>
          </div>
          <div class="workspace-heading__mark">
            <Sprout :size="21" />
            <span>按季节校核</span>
          </div>
        </header>

        <div v-if="!workspace.state.backendOnline && !workspace.state.loading" class="connection-caution">
          <strong>尚未连接到本地档案服务</strong>
          <span>请从仓库根目录启动 Python 服务后刷新页面。</span>
        </div>

        <CatalogView v-if="workspace.state.active === 'catalog'" />
        <ObservationView v-else-if="workspace.state.active === 'observation'" />
        <ComparisonView v-else-if="workspace.state.active === 'comparison'" />
        <BriefView v-else />
      </main>
    </div>

    <ToastStack
      :notices="workspace.state.notices"
      @dismiss="workspace.dismissNotice"
    />
  </div>
</template>
