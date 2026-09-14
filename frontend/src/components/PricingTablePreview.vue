<!-- Copyright (c) 2026 PayGlue by André Nünninghoff -->
<!-- Licensed under the Business Source License 1.1, see LICENSE.md -->
<script setup lang="ts">
// PG-323: the table as a reader will see it, rendered by the same script
// the embed uses, so the preview cannot drift from the real thing. The
// script fetches its config from the API; inside the frame we hand it the
// form state instead, so nothing has to be saved to look at it.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiBaseUrl } from '../lib/publicUrls'

const props = defineProps<{ config: Record<string, unknown> }>()

const height = ref(320)
const frame = ref<HTMLIFrameElement | null>(null)

const srcdoc = computed(() => {
  // A closing script tag inside a tier name would end the inline script early.
  const json = JSON.stringify(props.config).replace(/<\//g, '<\\/')
  // The tag names are assembled so the SFC compiler does not read them as
  // blocks of this component.
  const S = 'script'
  const inline = `window.fetch=function(){return Promise.resolve({ok:true,json:function(){return Promise.resolve(${json})}})};`
    + `new ResizeObserver(function(){parent.postMessage({payglue:'preview-height',height:document.documentElement.scrollHeight},'*')}).observe(document.body);`
  return `<!doctype html><html><head><meta charset="utf-8"><${'style'}>html,body{margin:0;background:transparent}</${'style'}></head><body>`
    + `<${S}>${inline}</${S}>`
    + `<${S} src="${apiBaseUrl()}/pricing-table.js" data-table-id="preview"></${S}>`
    + `</body></html>`
})

function onMessage(event: MessageEvent) {
  const data = event.data
  if (!data || data.payglue !== 'preview-height') return
  if (frame.value && event.source !== frame.value.contentWindow) return
  const next = Number(data.height)
  if (Number.isFinite(next) && next > 0) height.value = Math.min(Math.max(next, 160), 1600)
}

onMounted(() => window.addEventListener('message', onMessage))
onBeforeUnmount(() => window.removeEventListener('message', onMessage))
</script>

<template>
  <iframe
    ref="frame"
    title="Pricing table preview"
    :srcdoc="srcdoc"
    sandbox="allow-scripts"
    class="w-full rounded-xl border-0 bg-transparent"
    :style="{ height: height + 'px' }"
  />
</template>
