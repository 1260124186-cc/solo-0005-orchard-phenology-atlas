<script setup lang="ts">
import { computed, ref } from "vue";
import {
  CheckCircle2,
  ChevronRight,
  Clock3,
  FilePlus2,
  MapPin,
  PencilLine,
  ShieldCheck,
  Sprout,
} from "@lucide/vue";
import EmptyState from "../components/EmptyState.vue";
import PlotForm from "../components/PlotForm.vue";
import TreeCard from "../components/TreeCard.vue";
import TreeForm from "../components/TreeForm.vue";
import { formatTimestamp } from "../domain/rules";
import { useWorkspace } from "../app/workspace";

const workspace = useWorkspace();
const selectedPlot = workspace.selectedPlot;
const selectedTreeId = ref<string | null>(null);
const selectedTree = computed(() =>
  selectedPlot.value?.trees.find(
    (tree) => tree.id === selectedTreeId.value,
  ) ?? selectedPlot.value?.trees[0] ?? null,
);

async function createPlot(payload: Record<string, unknown>) {
  const result = await workspace.runAction(
    () => workspace.createPlot(payload),
    "园区草稿已入档",
  );
  if (result) {
    await workspace.refreshPlots();
    await workspace.loadPlot(result.id);
  }
}

async function createTree(payload: Record<string, unknown>) {
  await workspace.runAction(
    () => workspace.createTree(payload),
    "植株已加入园区",
  );
}

async function confirmPlot() {
  const plot = selectedPlot.value;
  if (!plot) return;
  await workspace.runAction(
    () => workspace.confirmSelectedPlot(plot.revision),
    "园区档案已确认并锁定",
  );
}

function selectTree(tree: { id: string }) {
  selectedTreeId.value = tree.id;
}
</script>

<template>
  <section class="work-surface catalog-surface">
    <div class="surface-column surface-column--index">
      <div class="section-heading">
        <div>
          <span class="eyebrow">档案索引</span>
          <h2>园区与重点品种</h2>
        </div>
        <FilePlus2 :size="21" />
      </div>

      <div v-if="workspace.state.plots.length" class="plot-index">
        <button
          v-for="plot in workspace.state.plots"
          :key="plot.id"
          type="button"
          class="plot-index__item"
          :class="{ 'is-active': workspace.state.selectedPlotId === plot.id }"
          data-check="plot-list-item"
          @click="workspace.selectPlot(plot.id)"
        >
          <span class="plot-index__status" :class="`is-${plot.status}`">
            <CheckCircle2 v-if="plot.status === 'confirmed'" :size="14" />
            <Clock3 v-else :size="14" />
          </span>
          <span class="plot-index__copy">
            <small>{{ plot.code }}</small>
            <strong>{{ plot.name }}</strong>
            <span>{{ plot.cultivar_focus }} · {{ plot.tree_count }} 株</span>
          </span>
          <ChevronRight :size="17" />
        </button>
      </div>

      <EmptyState
        v-else
        title="尚无园区档案"
        description="先在右侧建立第一个园区草稿，再逐株编目。"
      />

      <div class="paper-note">
        <PencilLine :size="17" />
        <p>园区确认后不可直接改写，核查人应以完整档案为准。</p>
      </div>
    </div>

    <div class="surface-column surface-column--work">
      <template v-if="selectedPlot">
        <div class="plot-folio">
          <div class="plot-folio__header">
            <div>
              <span class="folio-code">{{ selectedPlot.code }}</span>
              <h2>{{ selectedPlot.name }}</h2>
              <p>
                <MapPin :size="15" />
                {{ selectedPlot.locality }}
              </p>
            </div>
            <span
              class="status-stamp"
              :class="`is-${selectedPlot.status}`"
              data-check="plot-status"
            >
              {{ selectedPlot.status === "confirmed" ? "已确认" : "草稿中" }}
            </span>
          </div>

          <div class="folio-facts">
            <div>
              <span>重点品种</span>
              <strong>{{ selectedPlot.cultivar_focus }}</strong>
            </div>
            <div>
              <span>档案责任人</span>
              <strong>{{ selectedPlot.steward }}</strong>
            </div>
            <div>
              <span>起始种植</span>
              <strong>{{ selectedPlot.planting_year }}</strong>
            </div>
            <div>
              <span>最近修订</span>
              <strong>{{ formatTimestamp(selectedPlot.updated_at) }}</strong>
            </div>
          </div>

          <p class="folio-note">
            {{ selectedPlot.note || "尚未补充档案说明。" }}
          </p>
        </div>

        <div class="tree-section">
          <div class="section-heading section-heading--compact">
            <div>
              <span class="eyebrow">植株目录</span>
              <h3>{{ selectedPlot.trees.length }} 株在册记录</h3>
            </div>
            <Sprout :size="20" />
          </div>
          <div v-if="selectedPlot.trees.length" class="tree-list">
            <TreeCard
              v-for="tree in selectedPlot.trees"
              :key="tree.id"
              :tree="tree"
              :selected="selectedTree?.id === tree.id"
              @select="selectTree"
            />
          </div>
          <EmptyState
            v-else
            title="园区还没有植株"
            description="至少加入一株在册果树后，才能确认园区档案。"
          />
        </div>

        <aside v-if="selectedTree" class="tree-focus">
          <div>
            <span class="eyebrow">当前植株</span>
            <strong>{{ selectedTree.code }} · {{ selectedTree.cultivar }}</strong>
            <small>{{ selectedTree.rootstock }} / {{ selectedTree.planting_year }} 年定植</small>
          </div>
          <p>{{ selectedTree.note || "没有补充说明。" }}</p>
        </aside>

        <TreeForm
          v-if="selectedPlot.status === 'draft'"
          :plot="selectedPlot"
          @create="createTree"
        />

        <div class="confirmation-band">
          <div class="confirmation-band__copy">
            <ShieldCheck :size="22" />
            <div>
              <strong>确认后冻结园区基础信息</strong>
              <span>植株历史与季节志仍可继续追加。</span>
            </div>
          </div>
          <button
            type="button"
            class="button button--primary"
            data-check="confirm-plot"
            :disabled="
              selectedPlot.status !== 'draft' ||
              selectedPlot.trees.length === 0
            "
            @click="confirmPlot"
          >
            <ShieldCheck :size="17" />
            {{
              selectedPlot.status === "confirmed"
                ? "园区已确认"
                : "确认园区档案"
            }}
          </button>
        </div>
      </template>

      <template v-else>
        <div class="new-plot-folio">
          <div class="section-heading">
            <div>
              <span class="eyebrow">建立档案</span>
              <h2>新建园区草稿</h2>
            </div>
            <FilePlus2 :size="21" />
          </div>
          <p class="section-lead">
            先记录园区的来源与管护背景，再逐株建立可比较的物候档案。
          </p>
          <PlotForm @create="createPlot" />
        </div>
      </template>
    </div>
  </section>
</template>
