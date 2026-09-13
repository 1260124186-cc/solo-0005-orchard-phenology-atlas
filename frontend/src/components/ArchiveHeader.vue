<script setup lang="ts">
import { Database, LoaderCircle, Trees } from "@lucide/vue";

defineProps<{
  online: boolean;
  loading: boolean;
}>();
</script>

<template>
  <header class="archive-header">
    <div class="archive-brand">
      <div class="archive-brand__seal" aria-hidden="true">
        <Trees :size="27" :stroke-width="1.6" />
      </div>
      <div>
        <span>地方品种档案</span>
        <strong>果园物候图谱编研台</strong>
      </div>
    </div>

    <div class="archive-meta">
      <div class="archive-meta__item">
        <span>季节编号</span>
        <strong>{{ new Date().getFullYear() }}</strong>
      </div>
      <div class="archive-meta__item">
        <span>本地快照</span>
        <strong class="online-state" :class="{ 'is-online': online }">
          <Database :size="14" />
          {{ online ? "已连接" : "未连接" }}
        </strong>
      </div>
      <LoaderCircle
        v-if="loading"
        class="header-spinner"
        :size="22"
        aria-label="正在处理"
      />
    </div>
  </header>
</template>
