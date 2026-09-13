<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import {
  CalendarDays,
  Check,
  CircleDashed,
  Eraser,
  LoaderCircle,
  Plus,
  Sprout,
} from "@lucide/vue";
import EmptyState from "../components/EmptyState.vue";
import ChoiceField from "../components/ChoiceField.vue";
import ObservationStageForm from "../components/ObservationStageForm.vue";
import StageTrack from "../components/StageTrack.vue";
import { formatTimestamp, missingRequiredStages } from "../domain/rules";
import { completedProgress, stageLabel } from "../domain/stages";
import type { ObservationSummary, TreeRecord } from "../domain/types";
import { useWorkspace } from "../app/workspace";

const workspace = useWorkspace();
const selectedObservation = workspace.selectedObservation;
const startForm = reactive({
  plotId: "",
  treeId: "",
  season: String(new Date().getFullYear()),
  observer: "",
  note: "",
});
const startErrors = ref<string[]>([]);

const activeTrees = computed<TreeRecord[]>(() => {
  const plot = startForm.plotId
    ? workspace.state.plotDetails[startForm.plotId]
    : null;
  return plot?.trees.filter((tree) => tree.status === "active") ?? [];
});

const completed = computed(() =>
  workspace.state.observations.filter((item) => item.status === "completed"),
);
const plotChoices = computed(() =>
  workspace.state.plots.map((plot) => ({
    value: plot.id,
    label: `${plot.code} · ${plot.name}`,
  })),
);
const treeChoices = computed(() =>
  activeTrees.value.map((tree) => ({
    value: tree.id,
    label: `${tree.code} · ${tree.cultivar}`,
  })),
);

watch(
  () => workspace.state.selectedPlotId,
  (plotId) => {
    if (plotId && !startForm.plotId) {
      startForm.plotId = plotId;
    }
  },
  { immediate: true },
);

watch(
  () => startForm.plotId,
  async (plotId) => {
    if (!plotId) return;
    if (!workspace.state.plotDetails[plotId]) {
      await workspace.runAction(
        () => workspace.loadPlot(plotId),
        "园区植株目录已载入",
      );
    }
    startForm.treeId = activeTrees.value[0]?.id ?? "";
  },
);

async function startObservation() {
  startErrors.value = [];
  if (!startForm.plotId) startErrors.value.push("请选择园区");
  if (!startForm.treeId) startErrors.value.push("请选择在册植株");
  if (!startForm.observer.trim()) startErrors.value.push("请填写观察者");
  if (startErrors.value.length) return;
  const result = await workspace.runAction(
    () =>
      workspace.startObservation({
        tree_id: startForm.treeId,
        season: startForm.season,
        observer: startForm.observer,
        note: startForm.note,
      }),
    "季节志已建立，可以开始补录阶段",
  );
  if (result) {
    workspace.selectObservation(result.id);
  }
}

async function addStage(payload: Record<string, unknown>) {
  const current = workspace.selectedObservation.value;
  if (!current) return;
  await workspace.runAction(
    () => workspace.addStage(current, payload),
    "物候阶段已补录",
  );
}

async function removeStage(stage: string) {
  const current = workspace.selectedObservation.value;
  if (!current) return;
  await workspace.runAction(
    () => workspace.removeStage(current, stage),
    "物候阶段已移除",
  );
}

async function completeObservation() {
  const current = workspace.selectedObservation.value;
  if (!current) return;
  const missing = missingRequiredStages(current);
  if (missing.length) {
    workspace.pushNotice("error", `还需记录：${missing.join("、")}`);
    return;
  }
  await workspace.runAction(
    () => workspace.completeObservation(current),
    "季节志已完成并冻结",
  );
}
</script>

<template>
  <section class="work-surface observation-surface">
    <div class="surface-column surface-column--work observation-main">
      <div class="section-heading">
        <div>
          <span class="eyebrow">季节编录</span>
          <h2>沿物候顺序补录观察</h2>
        </div>
        <CalendarDays :size="21" />
      </div>

      <div v-if="selectedObservation" class="season-sheet">
        <header class="season-sheet__header">
          <div>
            <span class="season-sheet__year">{{ selectedObservation.season }}</span>
            <h3>
              {{ selectedObservation.tree_code }} ·
              {{ selectedObservation.cultivar }}
            </h3>
            <p>
              观察者 {{ selectedObservation.observer }} ·
              建立于 {{ formatTimestamp(selectedObservation.created_at) }}
            </p>
          </div>
          <span
            class="status-stamp"
            :class="
              selectedObservation.status === 'completed'
                ? 'is-confirmed'
                : 'is-draft'
            "
            data-check="season-status"
          >
            {{
              selectedObservation.status === "completed"
                ? "季节志已完成"
                : "记录中"
            }}
          </span>
        </header>

        <div class="progress-ribbon">
          <div>
            <strong>{{ completedProgress(selectedObservation.entries) }}%</strong>
            <span>完成所需阶段</span>
          </div>
          <div class="progress-ribbon__bar">
            <i
              :style="{
                width: `${completedProgress(selectedObservation.entries)}%`,
              }"
            />
          </div>
        </div>

        <StageTrack :observation="selectedObservation" />

        <div
          v-if="selectedObservation.entries.length"
          class="stage-book"
          data-check="stage-entry-list"
        >
          <div
            v-for="entry in selectedObservation.entries"
            :key="entry.id"
            class="stage-book__row"
            data-check="stage-entry"
          >
            <span class="stage-book__stage">{{ stageLabel(entry.stage) }}</span>
            <span>{{ entry.observed_on }}</span>
            <span>置信 {{ entry.confidence }} / 5</span>
            <span class="stage-book__note">{{ entry.note || "无补充说明" }}</span>
            <button
              v-if="selectedObservation.status === 'open'"
              type="button"
              class="icon-button"
              aria-label="移除阶段"
              data-check="remove-stage"
              @click="removeStage(entry.stage)"
            >
              <Eraser :size="16" />
            </button>
          </div>
        </div>

        <ObservationStageForm
          v-if="selectedObservation.status === 'open'"
          :observation="selectedObservation"
          @add="addStage"
        />

        <div v-if="selectedObservation.status === 'open'" class="completion-band">
          <div>
            <Check :size="20" />
            <span>完成前需具备萌芽期、盛花期、坐果期与采收期。</span>
          </div>
          <button
            type="button"
            class="button button--primary"
            data-check="complete-season"
            @click="completeObservation"
          >
            <Check :size="17" />
            完成季节志
          </button>
        </div>
      </div>

      <EmptyState
        v-else-if="workspace.state.observations.length"
        title="请从右侧选择季节志"
        description="已有季节志仍可查阅；进入记录后可继续补录阶段。"
      />

      <EmptyState
        v-else
        title="还没有季节志"
        description="先在右侧选择园区和植株，建立本季第一条观察。"
      />
    </div>

    <aside class="surface-column surface-column--index observation-index">
      <div class="section-heading section-heading--compact">
        <div>
          <span class="eyebrow">建志入口</span>
          <h3>选择植株与季节</h3>
        </div>
        <Plus :size="20" />
      </div>

      <form class="season-start-form" @submit.prevent="startObservation">
        <label>
          <span>园区</span>
          <ChoiceField
            v-model="startForm.plotId"
            data-check="season-plot"
            :choices="plotChoices"
            placeholder="请选择园区"
          />
        </label>
        <label>
          <span>在册植株</span>
          <ChoiceField
            v-model="startForm.treeId"
            data-check="season-tree"
            :choices="treeChoices"
            placeholder="请选择植株"
            :disabled="treeChoices.length === 0"
          />
        </label>
        <div class="form-grid form-grid--two">
          <label>
            <span>季节年份</span>
            <input
              v-model="startForm.season"
              data-check="season-year"
              inputmode="numeric"
              maxlength="4"
            />
          </label>
          <label>
            <span>观察者</span>
            <input
              v-model="startForm.observer"
              data-check="season-observer"
              maxlength="80"
              placeholder="姓名或小组"
            />
          </label>
        </div>
        <label>
          <span>起始说明</span>
          <textarea
            v-model="startForm.note"
            rows="2"
            maxlength="500"
            placeholder="记录本季观察背景，可选"
          />
        </label>
        <div v-if="startErrors.length" class="form-errors">
          <span v-for="error in startErrors" :key="error">{{ error }}</span>
        </div>
        <button
          type="submit"
          class="button button--primary button--wide"
          data-check="start-season"
        >
          <Sprout :size="17" />
          建立季节志
        </button>
      </form>

      <div class="season-list-heading">
        <span>全部季节志</span>
        <small>{{ completed.length }} 份已完成</small>
      </div>
      <div class="observation-index__list">
        <button
          v-for="observation in workspace.state.observations"
          :key="observation.id"
          type="button"
          class="observation-index__item"
          :class="{ 'is-active': workspace.state.selectedObservationId === observation.id }"
          data-check="observation-list-item"
          @click="workspace.selectObservation(observation.id)"
        >
          <span class="observation-index__icon">
            <LoaderCircle v-if="observation.status === 'open'" :size="16" />
            <Check v-else :size="16" />
          </span>
          <span>
            <strong>{{ observation.season }} · {{ observation.tree_code }}</strong>
            <small>{{ observation.cultivar }}</small>
          </span>
          <CircleDashed v-if="observation.status === 'open'" :size="14" />
        </button>
      </div>
    </aside>
  </section>
</template>
