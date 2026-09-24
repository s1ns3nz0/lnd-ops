<script setup lang="ts">
defineProps<{versions: string, platforms: string, verified: string, commit: string, status: string, scope: string}>()
</script>

<template>
  <dl class="metadata-card">
    <div><dt>관련 버전</dt><dd>{{ versions }}</dd></div>
    <div><dt>검증 플랫폼</dt><dd>{{ platforms }}</dd></div>
    <div><dt>마지막 검증</dt><dd>{{ verified }}</dd></div>
    <div><dt>근거 커밋</dt><dd><code>{{ commit }}</code></dd></div>
    <div><dt>상태</dt><dd><span class="status-dot" />{{ status }}</dd></div>
    <div><dt>적용 범위</dt><dd>{{ scope }}</dd></div>
  </dl>
</template>
