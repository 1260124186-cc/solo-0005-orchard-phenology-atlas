<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import {
  ArrowLeftRight,
  CalendarCheck2,
  GitCompareArrows,
  MoveHorizontal,
} from "@lucide/vue";
import EmptyState from "../components/EmptyState.vue";
import ChoiceField from "../components/ChoiceField.vue";
import StageTrack from "../components/StageTrack.vue";
import { canCompareObservations, formatOffset, formatTimestamp } from "../domain/rules";
import { useWorkspace } from "../app/workspace";

const workspace = useWorkspace();
const selectedComparison = workspace.selectedComparison;
const form = reactive({
  leftId: "",
  rightId: "",
  title: "",
});

const completed = computed(() =>
  workspace.state.observations.filter((item) => item.status === "completed"),
);

const leftObservation = computed(
  () => completed.value.find((item) => item.id === form.leftId) ?? null,
);
const rightObservation = computed(
  () => completed.value.find((item) => item.id === form.rightId) ?? null,
);

const comparisonReady = computed(() =>
  canCompareObservations(leftObservation.value, rightObservation.value),
);
const observationChoices = computed(() =>
  completed.value.map((item) => ({
    value: item.id,
    label: `${item.season} · ${item.tree_code} · ${item.cultivar}`,
    disabled: item.id === form.rightId || item.id === form.leftId,
  })),
);
const leftChoices = computed(() =>
  observationChoices.value.map((item) => ({
    ...item,
    disabled: item.value === form.rightId,
  })),
);
const rightChoices = computed(() =>
  observationChoices.value.map((item) => ({
    ...item,
    disabled: item.value === form.leftId,
  })),
);

watch(
  completed,
  (items) => {
    if (!form.leftId && items[0]) form.leftId = items[0].id;
    if ((!form.rightId || form.rightId === form.leftId) && items[1]) {
      form.rightId = items[1].id;
    }
    if (!form.title && items[0] && items[1]) {
      form.title = `${items[0].season} 年 ${items[0].cultivar} 与 ${items[1].cultivar} 物候对齐`;
    }
  },
  { immediate: true },
);

watch(
  () => [form.leftId, form.rightId, leftObservation.value?.cultivar, rightObservation.value?.cultivar],
  () => {
    if (leftObservation.value && rightObservation.value) {
      form.title = `${leftObservation.value.season} 年 ${leftObservation.value.cultivar} 与 ${rightObservation.value.cultivar} 物候对齐`;
    }
  },
);

async function createComparison() {
  if (!comparisonReady.value) return;
  await workspace.runAction(
    () =>
      workspace.createComparison({
        title: form.title,
        left_observation_id: form.leftId,
        right_observation_id: form.rightId,
      }),
    "对比图谱已生成并保存",
  );
}
</script>

<template>
  <section class="comparison-surface">
    <div class="comparison-composer">
      <div class="section-heading">
        <div>
          <span class="eyebrow">季节对齐</span>
          <h2>选择两份已完成季节志</h2>
        </div>
        <GitCompareArrows :size="22" />
      </div>
      <p class="section-lead">
        只比较双方共同记录到的阶段；缺失项跳过，不进行推断。
      </p>

      <form class="comparison-form" @submit.prevent="createComparison">
        <div class="comparison-selectors">
          <label>
            <span>左侧季节志</span>
            <ChoiceField
              v-model="form.leftId"
              data-check="left-observation"
              :choices="leftChoices"
              placeholder="请选择季节志"
            />
          </label>
          <ArrowLeftRight :size="20" />
          <label>
            <span>右侧季节志</span>
            <ChoiceField
              v-model="form.rightId"
              data-check="right-observation"
              :choices="rightChoices"
              placeholder="请选择季节志"
            />
          </label>
        </div>
        <label>
          <span>图谱标题</span>
          <input
            v-model="form.title"
            data-check="comparison-title"
            maxlength="100"
          />
        </label>
        <div v-if="leftObservation && rightObservation && !comparisonReady" class="precondition-note">
          {{
            leftObservation.season !== rightObservation.season
              ? "两份季节志年份不同，无法对齐。"
              : "两份季节志没有共同阶段。"
          }}
        </div>
        <button
          type="submit"
          class="button button--primary"
          data-check="create-comparison"
          :disabled="!comparisonReady"
        >
          <GitCompareArrows :size="17" />
          生成对比图谱
        </button>
      </form>
    </div>

    <div v-if="selectedComparison" class="comparison-result" data-check="comparison-result">
      <header class="comparison-result__header">
        <div>
          <span class="eyebrow">已保存图谱</span>
          <h2>{{ selectedComparison.title }}</h2>
          <p>{{ formatTimestamp(selectedComparison.created_at) }}</p>
        </div>
        <span class="comparison-seal">
          <CalendarCheck2 :size="18" />
          {{ selectedComparison.season }}
        </span>
      </header>

      <p class="comparison-sentence" data-check="comparison-sentence">
        {{ selectedComparison.summary.sentence }}
      </p>

      <div class="comparison-pair">
        <div>
          <span>左侧</span>
          <strong>{{ selectedComparison.left_label }}</strong>
        </div>
        <MoveHorizontal :size="21" />
        <div>
          <span>右侧</span>
          <strong>{{ selectedComparison.right_label }}</strong>
        </div>
      </div>

      <div class="offset-book">
        <div class="offset-book__head">
          <span>阶段</span>
          <span>左侧日期</span>
          <span>右侧日期</span>
          <span>相对偏移</span>
          <span>置信差</span>
        </div>
        <div
          v-for="offset in selectedComparison.stage_offsets"
          :key="offset.stage"
          class="offset-book__row"
          data-check="offset-row"
        >
          <strong>{{ offset.label }}</strong>
          <span>{{ offset.left_date }}</span>
          <span>{{ offset.right_date }}</span>
          <span
            class="offset-pill"
            :class="{
              'is-early': offset.offset_days < 0,
              'is-late': offset.offset_days > 0,
            }"
          >
            {{ formatOffset(offset.offset_days) }}
          </span>
          <span>{{ offset.confidence_gap }}</span>
        </div>
      </div>

      <div class="comparison-stats">
        <div>
          <strong>{{ selectedComparison.summary.common_stage_count }}</strong>
          <span>共同阶段</span>
        </div>
        <div>
          <strong>{{ selectedComparison.summary.average_offset_days }}</strong>
          <span>平均偏移 / 天</span>
        </div>
        <div>
          <strong>{{ selectedComparison.summary.direction }}</strong>
          <span>总体方向</span>
        </div>
        <div>
          <strong>{{ selectedComparison.summary.stability }}</strong>
          <span>离散判断</span>
        </div>
      </div>

      <div class="comparison-tracks">
        <div>
          <span>{{ selectedComparison.left_label }}</span>
          <StageTrack
            :observation="
              completed.find(
                (item) => item.id === selectedComparison?.left_observation_id,
              ) ?? null
            "
            compact
          />
        </div>
        <div>
          <span>{{ selectedComparison.right_label }}</span>
          <StageTrack
            :observation="
              completed.find(
                (item) => item.id === selectedComparison?.right_observation_id,
              ) ?? null
            "
            compact
          />
        </div>
      </div>
    </div>

    <EmptyState
      v-else
      title="尚无对比图谱"
      description="完成两份同年季节志后，可以选择并生成确定性对齐结果。"
    />
  </section>
</template>
