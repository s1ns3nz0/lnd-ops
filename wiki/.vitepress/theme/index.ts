import DefaultTheme from 'vitepress/theme'
import type {Theme} from 'vitepress'
import MermaidDiagram from './MermaidDiagram.vue'
import OpsFlow from './OpsFlow.vue'
import MetadataCard from './MetadataCard.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({app}) {
    app.component('MermaidDiagram', MermaidDiagram)
    app.component('OpsFlow', OpsFlow)
    app.component('MetadataCard', MetadataCard)
  },
} satisfies Theme
