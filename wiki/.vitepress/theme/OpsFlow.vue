<script setup lang="ts">
import {ref} from 'vue'

const selected = ref(0)
const steps = [
  ['Observe', 'Prometheus 지표, Kubernetes Event, 허용된 로그를 수집한다.', '읽기 전용'],
  ['Diagnose', '고정된 PromQL과 버전이 붙은 runbook으로 원인을 좁힌다.', 'LLM 제안'],
  ['Recommend', '관측 사실, 가능 원인, 신뢰도, 권장 명령을 구조화한다.', 'LLM 제안'],
  ['Approve', '자금·지갑·영속 상태에 영향이 있으면 운영자가 결정한다.', '사람'],
  ['Act', '현재 자동 허용된 조치는 진단용 probe 재시작 하나뿐이다.', '정책 게이트'],
  ['Verify', '정책, workload, channel 신호가 원래 상태로 돌아왔는지 확인한다.', '결정적 검사'],
]
</script>

<template>
  <section class="ops-flow" aria-label="kagent 대응 단계 탐색기">
    <div class="ops-flow-buttons" role="tablist">
      <button v-for="(step, index) in steps" :key="step[0]" :class="{active: selected === index}"
        role="tab" :aria-selected="selected === index" @click="selected = index">
        <span>{{ index + 1 }}</span>{{ step[0] }}
      </button>
    </div>
    <div class="ops-flow-detail" role="tabpanel">
      <strong>{{ steps[selected][0] }}</strong>
      <p>{{ steps[selected][1] }}</p>
      <span>{{ steps[selected][2] }}</span>
    </div>
  </section>
</template>
