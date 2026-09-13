<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { Plus } from "@lucide/vue";
import { validateStageDraft } from "../domain/rules";
import { STAGES } from "../domain/stages";
import type { ObservationSummary, StageEntry } from "../domain/types";
import ChoiceField from "./ChoiceField.vue";

const props = defineProps<{
  observation: Pick<ObservationSummary, "entries">;
}>();

const emit = defineEmits<{
  add: [payload: Record<string, unknown>];
}>();

const today = new Date().toISOString().slice(0, 10);
const form = reactive({
  stage: "",
  observed_on: today,
  confidence: 4,
  note: "",
});
const errors = ref<string[]>([]);
const stageChoices = computed(() =>
  STAGES.map((stage) => ({
    value: stage.key,
    label: `${stage.label}${stage.required_for_completion ? " · 完成所需" : ""}`,
    disabled: props.observation.entries.some(
      (entry) => entry.stage === stage.key,
    ),
  })),
);

function submit() {
  const issues = validateStageDraft(
    form as Partial<StageEntry>,
    props.observation.entries,
  );
  errors.value = issues.map((issue) => issue.message);
  if (issues.length > 0) return;
  emit("add", { ...form });
  form.stage = "";
  form.note = "";
}
</script>

<template>
  <form class="stage-entry-form" @submit.prevent="submit">
    <div class="form-grid form-grid--four">
      <label>
        <span>物候阶段</span>
        <ChoiceField
          v-model="form.stage"
          data-check="stage-key"
          :choices="stageChoices"
          placeholder="请选择阶段"
        />
      </label>
      <label>
        <span>观察日期</span>
        <input v-model="form.observed_on" data-check="stage-date" type="date" />
      </label>
      <label>
        <span>置信度</span>
        <ChoiceField
          v-model="form.confidence"
          data-check="stage-confidence"
          :choices="[1, 2, 3, 4, 5].map((value) => ({
            value,
            label: `${value} / 5`,
          }))"
        />
      </label>
      <label>
        <span>现场说明</span>
        <input v-model="form.note" maxlength="300" placeholder="可选" />
      </label>
    </div>
    <div v-if="errors.length" class="form-errors">
      <span v-for="error in errors" :key="error">{{ error }}</span>
    </div>
    <button type="submit" class="button button--secondary" data-check="add-stage">
      <Plus :size="16" />
      补录阶段
    </button>
  </form>
</template>
