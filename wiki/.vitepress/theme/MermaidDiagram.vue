<script setup lang="ts">
import {nextTick, onMounted, ref, watch} from 'vue'
import {inBrowser} from 'vitepress'

const props = defineProps<{code: string, label: string}>()
const output = ref('')
const error = ref('')

async function render() {
  if (!inBrowser) return
  try {
    const {default: mermaid} = await import('mermaid')
    mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme: 'dark'})
    const id = `mermaid-${crypto.randomUUID()}`
    output.value = (await mermaid.render(id, props.code)).svg
    error.value = ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

onMounted(() => nextTick(render))
watch(() => props.code, render)
</script>

<template>
  <figure class="mermaid-frame" :aria-label="label">
    <div v-if="output" v-html="output" />
    <pre v-else-if="error">{{ error }}</pre>
    <p v-else>다이어그램을 불러오는 중…</p>
    <figcaption>{{ label }}</figcaption>
  </figure>
</template>
