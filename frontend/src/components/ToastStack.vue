<script setup lang="ts">
import { CircleCheck, CircleX, Info, X } from "@lucide/vue";

interface Notice {
  id: number;
  tone: "success" | "error" | "info";
  message: string;
}

defineProps<{
  notices: readonly Notice[];
}>();

defineEmits<{
  dismiss: [id: number];
}>();

function iconFor(tone: Notice["tone"]) {
  if (tone === "success") return CircleCheck;
  if (tone === "error") return CircleX;
  return Info;
}
</script>

<template>
  <div class="toast-stack" aria-live="polite">
    <div
      v-for="notice in notices"
      :key="notice.id"
      class="toast"
      :class="`toast--${notice.tone}`"
    >
      <component :is="iconFor(notice.tone)" :size="19" />
      <span>{{ notice.message }}</span>
      <button
        type="button"
        aria-label="关闭提示"
        @click="$emit('dismiss', notice.id)"
      >
        <X :size="15" />
      </button>
    </div>
  </div>
</template>
