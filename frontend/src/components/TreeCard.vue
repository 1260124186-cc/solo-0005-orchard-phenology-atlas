<script setup lang="ts">
import { CalendarDays, Sprout } from "@lucide/vue";
import type { TreeRecord } from "../domain/types";

defineProps<{
  tree: TreeRecord;
  selected?: boolean;
}>();

defineEmits<{
  select: [tree: TreeRecord];
}>();

const statusLabel: Record<TreeRecord["status"], string> = {
  active: "在册",
  retired: "已退休",
  lost: "已遗失",
};
</script>

<template>
  <button
    type="button"
    class="tree-card"
    :class="{ 'is-selected': selected }"
    data-check="tree-card"
    @click="$emit('select', tree)"
  >
    <span class="tree-card__icon">
      <Sprout :size="20" />
    </span>
    <span class="tree-card__main">
      <span class="tree-card__code">{{ tree.code }}</span>
      <strong>{{ tree.cultivar }}</strong>
      <small>{{ tree.rootstock || "砧木未记录" }}</small>
    </span>
    <span class="tree-card__side">
      <small>{{ statusLabel[tree.status] }}</small>
      <span>
        <CalendarDays :size="14" />
        {{ tree.planting_year }}
      </span>
    </span>
  </button>
</template>
