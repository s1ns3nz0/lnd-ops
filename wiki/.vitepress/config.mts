import {defineConfig} from 'vitepress'

const repo = 'https://github.com/s1ns3nz0/lnd-ops'

export default defineConfig({
  lang: 'ko-KR',
  title: 'LND Ops Wiki',
  description: 'LND의 운영 요구를 Kubernetes 설계, 관측, 보안, 자동 대응으로 연결하는 학습 Wiki',
  base: '/lnd-ops/',
  cleanUrls: true,
  lastUpdated: true,
  head: [['link', {rel: 'icon', href: '/lnd-ops/banner.png'}]],
  themeConfig: {
    logo: '/banner.png',
    siteTitle: 'LND Ops Wiki',
    search: {provider: 'local'},
    nav: [
      {text: '시작하기', link: '/start-here'},
      {text: 'LND 사용 흐름', link: '/01-foundations/lnd-workflow'},
      {text: 'Kubernetes 설계', link: '/03-kubernetes/stateful-design'},
      {text: '자동 대응', link: '/10-automation/observe-to-act'},
    ],
    sidebar: [
      {text: '시작', items: [{text: 'Wiki 소개', link: '/'}, {text: '안전하게 시작하기', link: '/start-here'}, {text: '학습 지도', link: '/roadmap'}]},
      {text: '1. Lightning과 LND', items: [{text: '사용 사례와 전체 흐름', link: '/01-foundations/lnd-workflow'}, {text: 'LND 구조와 상태', link: '/01-foundations/lnd-architecture'}]},
      {text: '2. 플랫폼 요구사항', items: [{text: '운영 요구 도출', link: '/02-requirements/operational-requirements'}]},
      {text: '3. Kubernetes 아키텍처', items: [{text: 'StatefulSet과 PVC', link: '/03-kubernetes/stateful-design'}]},
      {text: '4. 재현 가능한 배포', items: [{text: 'Helm과 멱등성', link: '/04-deployment/reproducible-helm'}]},
      {text: '5. 지갑과 키', items: [{text: '비밀과 복구 경계', link: '/05-wallet/wallet-boundaries'}]},
      {text: '6. 채널·유동성·결제', items: [{text: '운영 모델', link: '/06-payments/channel-liquidity'}]},
      {text: '7. 관측과 경보', items: [{text: '신호에서 판단까지', link: '/07-observability/signals-to-decisions'}]},
      {text: '8. 장애와 Runbook', items: [{text: '장애 대응 수명주기', link: '/08-incidents/runbook-lifecycle'}]},
      {text: '9. 보안과 복구', items: [{text: '심층 방어', link: '/09-security/defense-in-depth'}, {text: 'SCB 복구', link: '/09-security/scb-recovery'}]},
      {text: '10. kagent 자동 대응', items: [{text: 'Observe에서 Verify까지', link: '/10-automation/observe-to-act'}]},
      {text: '11. 운영 검증', items: [{text: '증거 기반 검증', link: '/11-validation/evidence'}]},
      {text: '12. 설계 회고', items: [{text: '한계와 다음 단계', link: '/12-retrospective/tradeoffs'}, {text: '우리가 내린 결정', link: '/decisions/'}]},
    ],
    socialLinks: [{icon: 'github', link: repo}],
    editLink: {pattern: `${repo}/edit/master/wiki/:path`, text: 'GitHub에서 이 페이지 편집'},
    footer: {message: '공식 원리, 프로젝트 판단, 구현, 검증, 제약을 구분해 기록합니다.', copyright: 'LND Ops'},
    outline: {level: [2, 3], label: '페이지 목차'},
    docFooter: {prev: '이전', next: '다음'},
    lastUpdated: {text: 'Git 기준 최근 변경'},
  },
})
