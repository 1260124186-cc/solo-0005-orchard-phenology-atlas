<script setup lang="ts">
import { Check, Circle } from "@lucide/vue";
import { STAGES, stageLabel } from "../domain/stages";
import type { ObservationSummary } from "../domain/types";

const props = withDefaults(
  defineProps<{
    observation?: ObservationSummary | null;
    compact?: boolean;
  }>(),
  {
    observation: null,
    compact: false,
  },
);

function entryFor(stage: string) {
  return props.observation?.entry_map[stage];
}

function stageState(stage: string): "done" | "missing-required" | "pending" {
  if (entryFor(stage)) return "done";
  const definition = STAGES.find((item) => item.key === stage);
  return definition?.required_for_completion ? "missing-required" : "pending";
}
</script>

<template>
  <div class="stage-track" :class="{ 'is-compact': compact }">
    <div
      v-for="stage in STAGES"
      :key="stage.key"
      class="stage-track__item"
      :class="`is-${stageState(stage.key)}`"
      :data-stage="stage.key"
    >
      <div class="stage-track__node">
        <Check v-if="stageState(stage.key) === 'done'" :size="13" :stroke-width="3" />
        <Circle v-else :size="8" fill="currentColor" />
      </div>
      <div class="stage-track__copy">
        <strong>{{ stageLabel(stage.key) }}</strong>
        <small v-if="entryFor(stage.key)">
          {{ entryFor(stage.key)?.observed_on }} · 置信 {{ entryFor(stage.key)?.confidence }}
        </small>
        <small v-else>{{ stage.required_for_completion ? "完成所需" : "可选记录" }}</small>
      </div>
    </div>
  </div>
</template>
