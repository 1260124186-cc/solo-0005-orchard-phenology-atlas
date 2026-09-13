<script setup lang="ts">
import { Archive, ArrowRight } from "@lucide/vue";

withDefaults(
  defineProps<{
    title: string;
    description: string;
    actionLabel?: string;
  }>(),
  {
    actionLabel: "",
  },
);

defineEmits<{
  action: [];
}>();
</script>

<template>
  <div class="empty-state">
    <div class="empty-state__icon">
      <Archive :size="28" :stroke-width="1.5" />
    </div>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <button
      v-if="actionLabel"
      type="button"
      class="text-action"
      @click="$emit('action')"
    >
      {{ actionLabel }}
      <ArrowRight :size="15" />
    </button>
  </div>
</template>
