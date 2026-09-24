import DefaultTheme from 'vitepress/theme'
import type {Theme} from 'vitepress'
import MermaidDiagram from './MermaidDiagram.vue'
import OpsFlow from './OpsFlow.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({app}) {
    app.component('MermaidDiagram', MermaidDiagram)
    app.component('OpsFlow', OpsFlow)
  },
} satisfies Theme
