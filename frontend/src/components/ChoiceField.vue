<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Check, ChevronDown } from "@lucide/vue";

interface Choice {
  value: string | number;
  label: string;
  disabled?: boolean;
}

const props = withDefaults(
  defineProps<{
    modelValue: string | number;
    choices: readonly Choice[];
    placeholder?: string;
    disabled?: boolean;
  }>(),
  {
    placeholder: "请选择",
    disabled: false,
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string | number];
}>();

const root = ref<HTMLElement | null>(null);
const open = ref(false);

const currentLabel = computed(
  () =>
    props.choices.find((choice) => choice.value === props.modelValue)?.label ??
    "",
);

function choose(choice: Choice) {
  if (choice.disabled) return;
  emit("update:modelValue", choice.value);
  open.value = false;
}

function closeFromOutside(event: PointerEvent) {
  if (root.value && !root.value.contains(event.target as Node)) {
    open.value = false;
  }
}

onMounted(() => document.addEventListener("pointerdown", closeFromOutside));
onBeforeUnmount(() =>
  document.removeEventListener("pointerdown", closeFromOutside),
);
</script>

<template>
  <div ref="root" class="choice-field">
    <button
      type="button"
      class="choice-field__trigger"
      :class="{ 'is-open': open, 'has-value': Boolean(currentLabel) }"
      :disabled="disabled"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span>{{ currentLabel || placeholder }}</span>
      <ChevronDown :size="15" />
    </button>
    <div v-if="open" class="choice-field__menu">
      <button
        v-for="choice in choices"
        :key="choice.value"
        type="button"
        class="choice-field__choice"
        :class="{ 'is-selected': choice.value === modelValue }"
        :disabled="choice.disabled"
        :data-choice-value="choice.value"
        @click="choose(choice)"
      >
        <span>{{ choice.label }}</span>
        <Check v-if="choice.value === modelValue" :size="14" />
      </button>
    </div>
  </div>
</template>
