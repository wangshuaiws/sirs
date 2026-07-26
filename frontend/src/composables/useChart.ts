import { shallowRef } from 'vue'
import * as echarts from 'echarts'

export function useChart() {
  const instance = shallowRef<echarts.ECharts | null>(null)
  let _resizeHandler: (() => void) | null = null

  function init(dom: HTMLElement) {
    if (instance.value) return
    instance.value = echarts.init(dom, 'dark')
    _resizeHandler = () => instance.value?.resize()
    window.addEventListener('resize', _resizeHandler)
  }

  function setOption(option: echarts.EChartsOption, notMerge?: boolean) {
    instance.value?.setOption(option, notMerge ?? false)
  }

  function dispose() {
    if (_resizeHandler) {
      window.removeEventListener('resize', _resizeHandler)
      _resizeHandler = null
    }
    if (instance.value) {
      instance.value.dispose()
      instance.value = null
    }
  }

  return { instance, init, setOption, dispose }
}
