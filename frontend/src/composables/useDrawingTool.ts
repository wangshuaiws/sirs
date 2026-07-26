import { shallowRef, ref } from 'vue'
import type { ShallowRef } from 'vue'
import type { ECharts } from 'echarts'
import { drawingApi } from '../api'

// ── 类型 ──
export interface AnchorPoint {
  dataIndex: number
  price: number
}

export interface Drawing {
  id: string
  type: ToolMode
  color: string
  anchorPoints: AnchorPoint[]
}

export type ToolMode = 'straight-line' | 'v-shape' | 'vertical-segment' | 'inverted-v-shape'
type Phase = 'ready' | 'dragging'

// ── 工具函数 ──
let _idCounter = 0
function genId(): string {
  return 'd' + (++_idCounter) + '_' + Date.now().toString(36)
}

function pointToSegmentDist(
  px: number, py: number,
  x1: number, y1: number,
  x2: number, y2: number,
): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return Math.hypot(px - x1, py - y1)
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

// ── composable ──
export function useDrawingTool(
  chartInstance: ShallowRef<ECharts | null>,
  klineData: ShallowRef<any[]>,
) {
  // 状态
  const drawingMode = shallowRef(false)
  const toolMode = shallowRef<ToolMode>('straight-line')
  const phase = shallowRef<Phase>('ready')
  const drawings = shallowRef<Drawing[]>([])
  const selectedColor = ref('#FFD700')
  const pendingPixelAnchor = shallowRef<{ x: number; y: number } | null>(null)
  const currentPixel = shallowRef<{ x: number; y: number } | null>(null)

  let _currentStockCode = ''
  let _saveTimer: ReturnType<typeof setTimeout> | null = null
  let _renderRaf = 0
  let _docMouseUp: ((e: MouseEvent) => void) | null = null

  // ── 坐标转换 ──
  function getChartDom(): HTMLElement | null {
    return chartInstance.value?.getDom() ?? null
  }

  function getEventChartPos(e: any): { x: number; y: number } | null {
    const dom = getChartDom()
    if (!dom) return null
    const rect = dom.getBoundingClientRect()
    const cx = e.event?.clientX ?? e.offsetX
    const cy = e.event?.clientY ?? e.offsetY
    return { x: cx - rect.left, y: cy - rect.top }
  }

  function pixelToData(x: number, y: number): AnchorPoint | null {
    const inst = chartInstance.value
    if (!inst) return null
    // 检查是否在 K线面板（grid 0）内
    if (!inst.containPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [x, y])) {
      // 启发式后备：面板 0 约占 2%-40% 高度
      const dom = getChartDom()
      if (dom) {
        const h = dom.clientHeight
        if (y < h * 0.02 || y > h * 0.40) return null
      } else {
        return null
      }
    }
    const result = inst.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [x, y])
    if (!result || !Array.isArray(result) || result.length < 2) return null
    const dataIndex = Math.round(result[0])
    const raw = klineData.value
    if (dataIndex < 0 || dataIndex >= raw.length) return null
    return { dataIndex, price: Number(result[1]) }
  }

  function dataToPixel(a: AnchorPoint): { x: number; y: number } | null {
    const inst = chartInstance.value
    if (!inst) return null
    const result = inst.convertToPixel(
      { xAxisIndex: 0, yAxisIndex: 0 },
      [a.dataIndex, a.price],
    )
    if (!result || !Array.isArray(result) || result.length < 2) return null
    return { x: result[0], y: result[1] }
  }

  function computeMirroredAnchor(apex: AnchorPoint, dragEnd: AnchorPoint): AnchorPoint {
    return {
      dataIndex: Math.round(2 * apex.dataIndex - dragEnd.dataIndex),
      price: dragEnd.price,
    }
  }

  // ── 事件处理 ──
  function handleMouseDown(e: any) {
    if (!drawingMode.value) return
    const pos = getEventChartPos(e)
    if (!pos) return
    const anchor = pixelToData(pos.x, pos.y)
    if (!anchor) return  // 不在 K线面板内

    phase.value = 'dragging'
    pendingPixelAnchor.value = pos
    currentPixel.value = pos

    // 在 document 上注册 mouseup，确保移出图表也能完成
    _docMouseUp = (me: MouseEvent) => {
      // 获取图表内的像素坐标
      const dom = getChartDom()
      if (!dom) return
      const rect = dom.getBoundingClientRect()
      handleMouseUp({ event: me, offsetX: me.clientX - rect.left, offsetY: me.clientY - rect.top })
    }
    document.addEventListener('mouseup', _docMouseUp)
  }

  function handleMouseMove(e: any) {
    if (!drawingMode.value) {
      // 正常模式：更新 mouseY 供浮动面板使用（由 KlineView 处理）
      return
    }
    if (phase.value !== 'dragging') return
    const pos = getEventChartPos(e)
    if (!pos) return
    currentPixel.value = pos
    scheduleRender()
  }

  function handleMouseUp(e: any) {
    if (!drawingMode.value || phase.value !== 'dragging') return
    phase.value = 'ready'
    currentPixel.value = null

    // 清理 document mouseup
    if (_docMouseUp) {
      document.removeEventListener('mouseup', _docMouseUp)
      _docMouseUp = null
    }

    const anchor = pendingPixelAnchor.value
    pendingPixelAnchor.value = null
    if (!anchor) return

    const pos = getEventChartPos(e)
    if (!pos) return

    // 最小拖拽距离
    const dx = pos.x - anchor.x
    const dy = pos.y - anchor.y
    if (Math.sqrt(dx * dx + dy * dy) < 5) return

    const endAnchor = pixelToData(pos.x, pos.y)
    if (!endAnchor) return

    const startAnchor = pixelToData(anchor.x, anchor.y)
    if (!startAnchor) return

    let drawing: Drawing
    const type = toolMode.value

    if (type === 'straight-line') {
      drawing = {
        id: genId(),
        type: 'straight-line',
        color: selectedColor.value,
        anchorPoints: [startAnchor, endAnchor],
      }
    } else if (type === 'vertical-segment') {
      // 竖直线：固定 dataIndex，只变价格
      drawing = {
        id: genId(),
        type: 'vertical-segment',
        color: selectedColor.value,
        anchorPoints: [
          { dataIndex: startAnchor.dataIndex, price: startAnchor.price },
          { dataIndex: startAnchor.dataIndex, price: endAnchor.price },
        ],
      }
    } else {
      // V: startAnchor 是底点，endAnchor 是拖动侧端点
      // 倒V: startAnchor 是顶点，endAnchor 是拖动侧端点
      const mirror = computeMirroredAnchor(startAnchor, endAnchor)
      // 按 dataIndex 排序左右
      const isV = type === 'v-shape'
      drawing = {
        id: genId(),
        type: isV ? 'v-shape' : 'inverted-v-shape',
        color: selectedColor.value,
        anchorPoints: [startAnchor, endAnchor, mirror],
      }
    }

    drawings.value = [...drawings.value, drawing]
    render()
    scheduleSave()
  }

  function handleContextMenu(e: any) {
    // 右击删除线条 —— 两种模式都生效
    const pos = getEventChartPos(e)
    if (!pos) return

    // 阻止浏览器默认右键菜单
    if (e.event) {
      e.event.preventDefault()
      e.event.stopPropagation()
    }

    const inst = chartInstance.value
    if (!inst || drawings.value.length === 0) return

    // 检查是否在 K线面板区域
    const dom = getChartDom()
    if (dom) {
      const h = dom.clientHeight
      if (pos.y < h * 0.02 || pos.y > h * 0.42) return
    }

    let minDist = Infinity
    let minIdx = -1

    for (let i = 0; i < drawings.value.length; i++) {
      const d = drawings.value[i]
      const apts = d.anchorPoints

      // 将 anchorPoints 转为像素坐标
      const pixels = apts.map(a => dataToPixel(a))

      if (d.type === 'straight-line' || d.type === 'vertical-segment') {
        // 单线段: anchorPoints[0] → anchorPoints[1]
        if (pixels[0] && pixels[1]) {
          const dist = pointToSegmentDist(pos.x, pos.y, pixels[0].x, pixels[0].y, pixels[1].x, pixels[1].y)
          if (dist < minDist) { minDist = dist; minIdx = i }
        }
      } else {
        // V / 倒V: apex(0) → tip(1)、apex(0) → tip(2)、中心竖线 apex(0) → (apex.x, tip.y)
        if (pixels[0] && pixels[1]) {
          const d1 = pointToSegmentDist(pos.x, pos.y, pixels[0].x, pixels[0].y, pixels[1].x, pixels[1].y)
          if (d1 < minDist) { minDist = d1; minIdx = i }
          // 中心竖线
          const dc = pointToSegmentDist(pos.x, pos.y, pixels[0].x, pixels[0].y, pixels[0].x, pixels[1].y)
          if (dc < minDist) { minDist = dc; minIdx = i }
        }
        if (pixels[0] && pixels[2]) {
          const d2 = pointToSegmentDist(pos.x, pos.y, pixels[0].x, pixels[0].y, pixels[2].x, pixels[2].y)
          if (d2 < minDist) { minDist = d2; minIdx = i }
        }
      }
    }

    if (minDist < 8 && minIdx >= 0) {
      const newDrawings = [...drawings.value]
      newDrawings.splice(minIdx, 1)
      drawings.value = newDrawings
      render()
      scheduleSave()
    }
  }

  // ── 渲染 ──
  function scheduleRender() {
    if (_renderRaf) return
    _renderRaf = requestAnimationFrame(() => {
      _renderRaf = 0
      render()
    })
  }

  function render() {
    const inst = chartInstance.value
    if (!inst) return
    const elements = buildGraphicElements()
    inst.setOption({ graphic: { elements } }, { replaceMerge: ['graphic'] })
  }

  function buildGraphicElements(): any[] {
    const elements: any[] = []

    // 已完成线条
    for (const d of drawings.value) {
      const e = drawingToGraphics(d)
      elements.push(...e)
    }

    // 预览线
    if (phase.value === 'dragging' && pendingPixelAnchor.value && currentPixel.value) {
      const preview = getPreviewGraphics()
      elements.push(...preview)
    }

    return elements
  }

  function drawingToGraphics(d: Drawing): any[] {
    const apts = d.anchorPoints
    const pixels = apts.map(a => dataToPixel(a))
    const lineStyle = {
      stroke: d.color,
      lineWidth: 1.5,
    }

    const baseProps = {
      type: 'line' as const,
      style: lineStyle,
      silent: true,
      z: 100,
    }

    if (d.type === 'straight-line' || d.type === 'vertical-segment') {
      if (!pixels[0] || !pixels[1]) return []
      return [{
        ...baseProps,
        shape: {
          x1: pixels[0].x, y1: pixels[0].y,
          x2: pixels[1].x, y2: pixels[1].y,
        },
      }]
    }

    // V / 倒V: 两条线从顶点出发 + 中心竖线
    const result: any[] = []
    if (pixels[0] && pixels[1]) {
      result.push({
        ...baseProps,
        shape: { x1: pixels[0].x, y1: pixels[0].y, x2: pixels[1].x, y2: pixels[1].y },
      })
      // 中心竖线: apex → 竖直延伸到与翼尖同高度
      result.push({
        type: 'line',
        shape: { x1: pixels[0].x, y1: pixels[0].y, x2: pixels[0].x, y2: pixels[1].y },
        style: lineStyle,
        silent: true,
        z: 100,
      })
    }
    if (pixels[0] && pixels[2]) {
      result.push({
        ...baseProps,
        shape: { x1: pixels[0].x, y1: pixels[0].y, x2: pixels[2].x, y2: pixels[2].y },
      })
    }
    return result
  }

  function getPreviewGraphics(): any[] {
    const anchor = pendingPixelAnchor.value!
    const curr = currentPixel.value!
    const type = toolMode.value
    const previewStyle = {
      stroke: selectedColor.value,
      lineWidth: 1.5,
      lineDash: [6, 3] as [number, number],
      opacity: 0.7,
    }

    if (type === 'straight-line') {
      return [{
        type: 'line',
        shape: { x1: anchor.x, y1: anchor.y, x2: curr.x, y2: curr.y },
        style: previewStyle,
        silent: true,
        z: 100,
      }]
    }

    if (type === 'vertical-segment') {
      return [{
        type: 'line',
        shape: { x1: anchor.x, y1: anchor.y, x2: anchor.x, y2: curr.y },
        style: previewStyle,
        silent: true,
        z: 100,
      }]
    }

    const mirrorX = 2 * anchor.x - curr.x
    const mirrorY = curr.y
    return [
      {
        type: 'line',
        shape: { x1: anchor.x, y1: anchor.y, x2: curr.x, y2: curr.y },
        style: previewStyle,
        silent: true,
        z: 100,
      },
      {
        type: 'line',
        shape: { x1: anchor.x, y1: anchor.y, x2: mirrorX, y2: mirrorY },
        style: previewStyle,
        silent: true,
        z: 100,
      },
      {
        type: 'line',
        shape: { x1: anchor.x, y1: anchor.y, x2: anchor.x, y2: curr.y },
        style: previewStyle,
        silent: true,
        z: 100,
      },
    ]
  }

  // ── zoom ──
  function onZoom() {
    if (drawings.value.length > 0) {
      scheduleRender()
    }
  }

  // ── 模式切换 ──
  function enterDrawingMode() {
    drawingMode.value = true
    toolMode.value = 'straight-line'
    phase.value = 'ready'
    const dom = getChartDom()
    if (dom) dom.style.cursor = 'crosshair'
  }

  function exitDrawingMode() {
    drawingMode.value = false
    phase.value = 'ready'
    pendingPixelAnchor.value = null
    currentPixel.value = null
    if (_docMouseUp) {
      document.removeEventListener('mouseup', _docMouseUp)
      _docMouseUp = null
    }
    const dom = getChartDom()
    if (dom) dom.style.cursor = ''
    // 清理预览
    render()
  }

  function setTool(mode: ToolMode) {
    toolMode.value = mode
  }

  function cancelDrag() {
    if (phase.value !== 'dragging') return
    phase.value = 'ready'
    pendingPixelAnchor.value = null
    currentPixel.value = null
    if (_docMouseUp) {
      document.removeEventListener('mouseup', _docMouseUp)
      _docMouseUp = null
    }
    render()
  }

  function clearAll() {
    drawings.value = []
    render()
    if (_currentStockCode) {
      drawingApi.delete(_currentStockCode).catch(() => {})
    }
  }

  // ── 持久化 ──
  function scheduleSave() {
    if (!_currentStockCode) return
    if (_saveTimer) clearTimeout(_saveTimer)
    _saveTimer = setTimeout(() => {
      _saveTimer = null
      drawingApi.save(_currentStockCode, drawings.value).catch(() => {})
    }, 300)
  }

  async function loadDrawings(stockCode: string) {
    _currentStockCode = stockCode
    try {
      const res: any = await drawingApi.get(stockCode)
      const data = res.data
      if (typeof data === 'string') {
        drawings.value = JSON.parse(data)
      } else if (Array.isArray(data)) {
        drawings.value = data
      } else {
        drawings.value = []
      }
    } catch {
      drawings.value = []
    }
  }

  function saveDrawings(stockCode: string) {
    if (_saveTimer) {
      clearTimeout(_saveTimer)
      _saveTimer = null
    }
    if (drawings.value.length > 0) {
      drawingApi.save(stockCode, drawings.value).catch(() => {})
    }
  }

  function detach() {
    if (_renderRaf) {
      cancelAnimationFrame(_renderRaf)
      _renderRaf = 0
    }
    if (_saveTimer) {
      clearTimeout(_saveTimer)
      _saveTimer = null
    }
    if (_docMouseUp) {
      document.removeEventListener('mouseup', _docMouseUp)
      _docMouseUp = null
    }
    const dom = getChartDom()
    if (dom) dom.style.cursor = ''
  }

  return {
    // 状态
    drawingMode,
    toolMode,
    phase,
    drawings,
    selectedColor,
    // 方法
    enterDrawingMode,
    exitDrawingMode,
    setTool,
    cancelDrag,
    clearAll,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
    handleContextMenu,
    onZoom,
    detach,
    // 持久化
    loadDrawings,
    saveDrawings,
  }
}
