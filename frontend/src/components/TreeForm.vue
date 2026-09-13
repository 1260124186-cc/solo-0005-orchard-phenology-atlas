<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { Plus } from "@lucide/vue";
import { validateTreeDraft } from "../domain/rules";
import type { PlotDetail, TreeRecord } from "../domain/types";

const props = defineProps<{
  plot: PlotDetail;
}>();

const emit = defineEmits<{
  create: [payload: Record<string, unknown>];
}>();

const form = reactive({
  code: "",
  cultivar: props.plot.cultivar_focus,
  rootstock: "未记录",
  planting_year: props.plot.planting_year,
  note: "",
});
const errors = ref<string[]>([]);

watch(
  () => props.plot.id,
  () => {
    form.code = `${props.plot.code}-T01`;
    form.cultivar = props.plot.cultivar_focus;
    form.planting_year = props.plot.planting_year;
    errors.value = [];
  },
  { immediate: true },
);

function submit() {
  const issues = validateTreeDraft(form as Partial<TreeRecord>);
  if (Number(form.planting_year) < props.plot.planting_year) {
    issues.push({
      field: "planting_year",
      message: "植株定植年份不能早于园区起始年份",
    });
  }
  errors.value = issues.map((issue) => issue.message);
  if (issues.length > 0) return;
  emit("create", {
    plot_id: props.plot.id,
    ...form,
  });
}
</script>

<template>
  <form class="archive-form archive-form--nested" @submit.prevent="submit">
    <div class="tree-form-heading">
      <strong>加入一株在册植株</strong>
      <span>编号需在当前园区内唯一</span>
    </div>
    <div class="form-grid form-grid--two">
      <label>
        <span>植株编号</span>
        <input v-model="form.code" data-check="tree-code" maxlength="17" />
      </label>
      <label>
        <span>品种名</span>
        <input v-model="form.cultivar" data-check="tree-cultivar" maxlength="80" />
      </label>
    </div>
    <div class="form-grid form-grid--three">
      <label>
        <span>砧木</span>
        <input v-model="form.rootstock" data-check="tree-rootstock" maxlength="80" />
      </label>
      <label>
        <span>定植年份</span>
        <input
          v-model.number="form.planting_year"
          data-check="tree-year"
          type="number"
        />
      </label>
      <label>
        <span>植株说明</span>
        <input v-model="form.note" maxlength="500" placeholder="可选" />
      </label>
    </div>
    <div v-if="errors.length" class="form-errors">
      <span v-for="error in errors" :key="error">{{ error }}</span>
    </div>
    <div class="form-actions">
      <button type="submit" class="button button--secondary" data-check="create-tree">
        <Plus :size="16" />
        加入植株
      </button>
    </div>
  </form>
</template>
