<script setup lang="ts">
import { reactive, ref } from "vue";
import { Plus, RotateCcw } from "@lucide/vue";
import { validatePlotDraft } from "../domain/rules";
import type { PlotSummary } from "../domain/types";

const emit = defineEmits<{
  create: [payload: Record<string, unknown>];
}>();

const year = new Date().getFullYear();
const form = reactive({
  code: "OR-1001",
  name: "",
  locality: "",
  cultivar_focus: "",
  steward: "",
  planting_year: year - 10,
  note: "",
});
const errors = ref<string[]>([]);

function submit() {
  const issues = validatePlotDraft(form as Partial<PlotSummary>);
  errors.value = issues.map((issue) => issue.message);
  if (issues.length > 0) return;
  emit("create", { ...form });
}

function reset() {
  form.code = "OR-1001";
  form.name = "";
  form.locality = "";
  form.cultivar_focus = "";
  form.steward = "";
  form.planting_year = year - 10;
  form.note = "";
  errors.value = [];
}
</script>

<template>
  <form class="archive-form" @submit.prevent="submit">
    <div class="form-grid form-grid--two">
      <label>
        <span>园区编号</span>
        <input
          v-model="form.code"
          data-check="plot-code"
          maxlength="11"
          placeholder="OR-1001"
        />
      </label>
      <label>
        <span>起始种植年份</span>
        <input
          v-model.number="form.planting_year"
          data-check="plot-year"
          type="number"
          min="1800"
          :max="year + 2"
        />
      </label>
    </div>
    <label>
      <span>园区名称</span>
      <input
        v-model="form.name"
        data-check="plot-name"
        maxlength="80"
        placeholder="例如：南坡地方梨园"
      />
    </label>
    <label>
      <span>地点描述</span>
      <input
        v-model="form.locality"
        data-check="plot-locality"
        maxlength="160"
        placeholder="村组、坡向或传统地名"
      />
    </label>
    <div class="form-grid form-grid--two">
      <label>
        <span>重点品种</span>
        <input
          v-model="form.cultivar_focus"
          data-check="plot-focus"
          maxlength="80"
          placeholder="品种名"
        />
      </label>
      <label>
        <span>责任人或机构</span>
        <input
          v-model="form.steward"
          data-check="plot-steward"
          maxlength="80"
          placeholder="档案责任人"
        />
      </label>
    </div>
    <label>
      <span>档案说明</span>
      <textarea
        v-model="form.note"
        data-check="plot-note"
        rows="3"
        maxlength="500"
        placeholder="记录地方名称、管理传统或待核事项"
      />
    </label>

    <div v-if="errors.length" class="form-errors" data-check="plot-errors">
      <span v-for="error in errors" :key="error">{{ error }}</span>
    </div>

    <div class="form-actions">
      <button type="submit" class="button button--primary" data-check="create-plot">
        <Plus :size="17" />
        建立园区草稿
      </button>
      <button type="button" class="button button--ghost" @click="reset">
        <RotateCcw :size="16" />
        清空
      </button>
    </div>
  </form>
</template>
