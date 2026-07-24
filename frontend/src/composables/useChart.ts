import { shallowRef } from 'vue'
import * as echarts from 'echarts'

export function useChart() {
  const instance = shallowRef<echarts.ECharts | null>(null)

  function init(dom: HTMLElement) {
    if (instance.value) return
    instance.value = echarts.init(dom, 'dark')
    window.addEventListener('resize', () => instance.value?.resize())
  }

  function setOption(option: echarts.EChartsOption) {
    instance.value?.setOption(option, true)
  }

  function dispose() {
    if (instance.value) {
      instance.value.dispose()
      instance.value = null
    }
  }

  return { instance, init, setOption, dispose }
}
