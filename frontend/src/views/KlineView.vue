<template>
  <div class="kline-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="search-box">
        <span class="search-box__icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        </span>
        <input ref="searchInputRef" v-model="keyword" type="text" class="search-box__input"
          placeholder="搜索股票代码或名称" @input="onSearchInput" @focus="showDropdown = true" @keydown="onSearchKeydown" />
        <div class="search-box__dropdown" v-if="showDropdown && (filteredResults.length || keyword)">
          <template v-if="filteredResults.length">
            <div v-for="(s, i) in filteredResults" :key="s.code" class="search-box__item"
              :class="{ 'search-box__item--active': i === activeIndex }" @click="selectStock(s)" @mouseenter="activeIndex = i">
              <span class="search-box__code">{{ s.code }}</span><span class="search-box__name">{{ s.name }}</span>
              <span :class="['badge', s.exchange === 'SH' ? 'badge--sh' : 'badge--sz']">{{ s.exchange === 'SH' ? '沪' : '深' }}</span>
            </div>
          </template>
          <div class="search-box__empty" v-else-if="keyword">未找到匹配股票</div>
        </div>
      </div>

      <div class="period-switch">
        <button v-for="p in periods" :key="p.value" class="period-switch__btn"
          :class="{ 'period-switch__btn--active': kline.period.value === p.value }"
          @click="onSwitchPeriod(p.value)">{{ p.label }}</button>
      </div>

      <div class="toolbar-right">
        <button ref="drawingBtnRef" class="tool-btn" :class="{ 'tool-btn--active': drawingTool.drawingMode.value }" title="画线" :disabled="!kline.stockInfo.value" @click="onToggleDrawingMode">✏️ 画线</button>
        <button class="adj-toggle" :class="{ 'adj-toggle--on': kline.adjusted.value }" @click="onToggleAdjusted">前复权</button>
      </div>
    </div>

    <!-- 登录对话框 -->
    <LoginDialog
      :visible="loginDialogVisible"
      @update:visible="loginDialogVisible = $event"
      @login-success="onLoginSuccess"
    />

    <!-- 股票信息头 -->
    <div ref="stockHeaderEl" class="stock-header" v-if="kline.stockInfo.value">
      <div class="stock-header__row1">
        <h2 class="stock-header__name">{{ kline.stockInfo.value.name }}</h2>
        <span class="stock-header__code">{{ kline.stockInfo.value.code }}</span>
        <button class="watchlist-btn" :class="{ 'watchlist-btn--added': inWatchlist, 'watchlist-btn--busy': watchlistBusy }"
          :title="inWatchlist ? '取消自选' : '加入自选'" @click="onToggleWatchlist" :disabled="watchlistBusy">
          <svg width="18" height="18" viewBox="0 0 24 24" :fill="inWatchlist ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
          </svg>
        </button>
      </div>
      <div class="stock-header__row2" v-if="kline.latestPrice.value">
        <div class="stock-header__price-section">
          <span class="stock-header__price" :class="kline.priceChangeClass.value">{{ kline.latestPrice.value.close }}</span>
          <span class="stock-header__change" :class="kline.priceChangeClass.value">{{ kline.priceChange.value >= 0 ? '+' : '' }}{{ kline.priceChange.value.toFixed(2) }}</span>
          <span class="stock-header__change-pct" :class="kline.priceChangeClass.value">{{ kline.priceChangePct.value }}%</span>
        </div>
        <div class="stock-header__meta">
          <div class="stock-header__meta-item"><span class="stock-header__meta-label">成交量</span><span class="stock-header__meta-value">{{ formatVolume(kline.latestPrice.value.volume) }}</span></div>
          <div class="stock-header__meta-item"><span class="stock-header__meta-label">成交额</span><span class="stock-header__meta-value">{{ formatAmount(kline.latestPrice.value.amount) }}</span></div>
        </div>
      </div>
    </div>

    <!-- K线图表 -->
    <div class="chart-section" v-if="kline.stockInfo.value">
      <!-- 指标选择 -->
      <div class="ma-tags" v-if="kline.klineData.value.length">
        <span class="indicator-btn" @click.stop="onToggleIndicatorMenu">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg>
        </span>
        <span class="ma-tags__sep">|</span>
        <!-- MA 模式 -->
        <template v-if="activeIndicator === 'ma'">
          <template v-for="(ma, i) in visibleMaConfigs" :key="ma.label">
            <span v-if="i > 0" class="ma-tags__sep">|</span>
            <span class="ma-tag" :style="{ color: ma.color }">
              {{ ma.label }}: {{ maValue(ma) }}
            </span>
          </template>
        </template>
        <!-- 知行合一模式 -->
        <template v-else>
          <span class="ma-tag" style="color:#FFFFFF">ZXDQ: {{ zxdqVal }}</span>
          <span class="ma-tags__sep">|</span>
          <span class="ma-tag" style="color:#FFD700">ZXDKX: {{ zxdkxVal }}</span>
        </template>
      </div>

      <!-- 指标面板标签 -->
      <div class="panel-labels" v-if="kline.klineData.value.length">
        <div class="panel-label" :style="{ top: getPanelTop('vol') }">
          <span class="panel-label__arrow">▼</span>
          <span class="panel-label__name">VOL(5,10)</span>
          <span class="panel-label__val">VOL: <b>{{ fmtVol(cursorVol) }}</b></span>
          <span class="panel-label__val">MA5: <b class="c-ma5">{{ fmtVol(cursorVolMa5) }}</b></span>
          <span class="panel-label__val">MA10: <b class="c-ma10">{{ fmtVol(cursorVolMa10) }}</b></span>
        </div>
        <div class="panel-label" :style="{ top: getPanelTop('macd') }">
          <span class="panel-label__arrow">▼</span>
          <span class="panel-label__name">MACD(12,26,9)</span>
          <span class="panel-label__val">DIF: <b class="c-dif">{{ fmtMACD(cursorDIF) }}</b></span>
          <span class="panel-label__val">DEA: <b class="c-dea">{{ fmtMACD(cursorDEA) }}</b></span>
          <span class="panel-label__val">MACD: <b :class="(cursorMACD ?? 0) >= 0 ? 'c-up' : 'c-down'">{{ fmtMACD(cursorMACD) }}</b></span>
        </div>
        <div class="panel-label" :style="{ top: getPanelTop('kdj') }">
          <span class="panel-label__arrow">▼</span>
          <span class="panel-label__name">KDJ(9,3,3)</span>
          <span class="panel-label__val">K: <b class="c-k">{{ fmtKDJ(cursorK) }}</b></span>
          <span class="panel-label__val">D: <b class="c-d">{{ fmtKDJ(cursorD) }}</b></span>
          <span class="panel-label__val">J: <b class="c-j">{{ fmtKDJ(cursorJ) }}</b></span>
        </div>
      </div>

      <!-- 浮动信息面板（跟随鼠标，不遮挡K线） -->
      <Teleport to="body">
        <div class="float-panel" v-if="isTracking && currentBar && !drawingTool.drawingMode.value" :style="floatPanelStyle">
          <div class="float-panel__row"><span>时间</span><strong>{{ currentBar.ts }}</strong></div>
          <div class="float-panel__row"><span>开盘价</span><strong>{{ fmtPrice(currentBar.open) }}</strong></div>
          <div class="float-panel__row"><span>最高价</span><strong>{{ fmtPrice(currentBar.high) }}</strong></div>
          <div class="float-panel__row"><span>最低价</span><strong>{{ fmtPrice(currentBar.low) }}</strong></div>
          <div class="float-panel__row"><span>收盘价</span><strong>{{ fmtPrice(currentBar.close) }}</strong></div>
          <div class="float-panel__row"><span>成交量</span><strong>{{ formatVolume(currentBar.volume) }}</strong></div>
          <div class="float-panel__row"><span>成交额</span><strong>{{ formatAmount(currentBar.amount) }}</strong></div>
          <div class="float-panel__row"><span>涨跌</span><strong :class="currentBarPriceClass">{{ currentBarChange }}</strong></div>
          <div class="float-panel__row"><span>振幅</span><strong>{{ currentBarAmplitude }}</strong></div>
          <div class="float-panel__row"><span>换手率</span><strong>{{ currentBarTurnoverRate }}</strong></div>
          <div class="float-panel__row"><span>流通股</span><strong>{{ currentBarFloatShare }}</strong></div>
        </div>
      </Teleport>

      <div ref="chartEl" class="chart-section__box"></div>
    </div>

    <div class="empty-state" v-else>
      <div class="empty-state__mark">◫</div>
      <p class="empty-state__title">选择股票查看K线</p>
      <p class="empty-state__desc">在上方搜索框输入 A 股代码或中文名称</p>
    </div>

    <!-- 指标下拉菜单 -->
    <Teleport to="body">
      <div class="indicator-menu" v-if="showIndicatorMenu" :style="indicatorMenuStyle" @click.stop>
        <div class="indicator-menu__item" @click="onSelectMA">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          <span>均线</span>
          <span class="indicator-menu__edit" @click.stop="onOpenMaEditor" title="编辑均线周期">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </span>
        </div>
        <div class="indicator-menu__item"
          :class="{ 'indicator-menu__item--active': activeIndicator === 'zhixingheyi' }"
          @click="onToggleZhixingheyi">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          <span>知行合一趋势线</span>
          <span v-if="activeIndicator === 'zhixingheyi'" class="indicator-menu__check">✓</span>
        </div>
      </div>
    </Teleport>

    <!-- MA 均线编辑器弹窗 -->
    <Teleport to="body">
      <div class="ma-editor-overlay" v-if="showMaEditor" @click.self="onCancelMaEdit">
        <div class="ma-editor">
          <div class="ma-editor__title">均线设置</div>
          <div class="ma-editor__row" v-for="(m, i) in maEditorValues" :key="maConfigs[i].label">
            <span class="ma-editor__dot" :style="{ background: maConfigs[i].color }"></span>
            <span class="ma-editor__label">{{ maConfigs[i].label }}</span>
            <input class="ma-editor__input" type="number" v-model.number="m.period" min="0" max="500" />
            <span class="ma-editor__unit">日</span>
          </div>
          <p class="ma-editor__hint">设为 0 则该线不显示</p>
          <div class="ma-editor__actions">
            <button class="ma-editor__btn ma-editor__btn--cancel" @click="onCancelMaEdit">取消</button>
            <button class="ma-editor__btn ma-editor__btn--confirm" @click="onConfirmMaEdit">确定</button>
          </div>
        </div>
      </div>
    </Teleport>
    <!-- 画线工具面板 -->
    <DrawingPanel
      :visible="drawingTool.drawingMode.value"
      :tool-mode="drawingTool.toolMode.value"
      :selected-color="drawingTool.selectedColor.value"
      :drawing-count="drawingTool.drawings.value.length"
      :panel-style="drawingPanelStyle"
      @select-tool="drawingTool.setTool"
      @update:selected-color="drawingTool.selectedColor.value = $event"
      @clear-all="drawingTool.clearAll()"
    />
  </div>
</template>

<script setup lang="ts">
import { shallowRef, ref, computed, onMounted, onUnmounted, watch, useTemplateRef } from 'vue'
import { useRoute } from 'vue-router'
import { useStockSearch } from '../composables/useStockSearch'
import { useKlineData } from '../composables/useKlineData'
import { useChart } from '../composables/useChart'
import { useDrawingTool } from '../composables/useDrawingTool'
import { useAuthStore } from '../stores/auth'
import LoginDialog from '../components/LoginDialog.vue'
import DrawingPanel from '../components/DrawingPanel.vue'
import { formatVolume, formatAmount } from '../composables/useFormat'
import { groupApi, stockApi } from '../api'

const periods = [{ label: '日K', value: 'daily' }, { label: '周K', value: 'weekly' }, { label: '月K', value: 'monthly' }]

const maConfigs = shallowRef([
  { label: 'MA5', period: 5, color: '#f8fafc' },
  { label: 'MA10', period: 10, color: '#fde047' },
  { label: 'MA20', period: 20, color: '#2196f3' },
  { label: 'MA60', period: 60, color: '#e63535' },
  { label: 'MA120', period: 120, color: '#f472b6' },
  { label: 'MA233', period: 233, color: '#a78bfa' },
])

const crossIdx = ref(-1)

// 指标菜单 & 编辑器状态
const showIndicatorMenu = shallowRef(false)
const showMaEditor = shallowRef(false)
const activeIndicator = shallowRef<'ma' | 'zhixingheyi'>('zhixingheyi')
const maEditorValues = shallowRef<{ period: number }[]>([])
const stockHeaderEl = useTemplateRef<HTMLElement>('stockHeaderEl')

const visibleMaConfigs = computed(() => maConfigs.value.filter(m => m.period > 0))

// 趋势线当前值（跟随十字光标移动，直接从 raw 读取接口字段）
const zxdqVal = computed(() => {
  const raw = kline.klineData.value; if (!raw.length) return '—'
  const r = raw[atIdx()]; return r?.zxdq != null ? (r.zxdq as number).toFixed(2) : '—'
})
const zxdkxVal = computed(() => {
  const raw = kline.klineData.value; if (!raw.length) return '—'
  const r = raw[atIdx()]; return r?.zxdkx != null ? (r.zxdkx as number).toFixed(2) : '—'
})

// 下拉菜单位置：stock-header 正中间
const indicatorMenuStyle = computed(() => {
  if (!stockHeaderEl.value) return { visibility: 'hidden' as const }
  const r = stockHeaderEl.value.getBoundingClientRect()
  return {
    position: 'fixed' as const,
    top: r.top + r.height / 2 + 'px',
    left: r.left + r.width / 2 + 'px',
    transform: 'translate(-50%, -50%)',
    zIndex: 100,
  }
})

// ── 自选股 ──
const inWatchlist = shallowRef(false)
const watchlistBusy = shallowRef(false)
let _watchlistGroupId: number | null = null

async function _getWatchlistGroupId(): Promise<number> {
  if (_watchlistGroupId) return _watchlistGroupId
  const res: any = await groupApi.list()
  const groups: any[] = res.data ?? []
  let g = groups.find((g: any) => g.name === '自选股')
  if (!g) {
    const cr: any = await groupApi.create({ name: '自选股' })
    g = cr.data
  }
  _watchlistGroupId = g.id as number
  return _watchlistGroupId
}

async function onToggleWatchlist() {
  const code = selectedCode.value; if (!code || watchlistBusy.value) return

  if (!store.isLoggedIn()) {
    loginDialogVisible.value = true
    return
  }

  watchlistBusy.value = true
  try {
    const gid = await _getWatchlistGroupId()
    if (inWatchlist.value) {
      await groupApi.removeStock(gid, code)
      inWatchlist.value = false
    } else {
      await groupApi.addStock(gid, code)
      inWatchlist.value = true
    }
  } catch { /* axios 拦截器已弹错误提示 */ }
  finally { watchlistBusy.value = false }
}

async function _checkWatchlist(code: string) {
  if (!store.isLoggedIn()) {
    inWatchlist.value = false
    return
  }
  try {
    const gid = await _getWatchlistGroupId()
    const res: any = await groupApi.getStocks(gid)
    const stocks: any[] = res.data ?? []
    inWatchlist.value = stocks.some((s: any) => s.code === code)
  } catch { inWatchlist.value = false }
}

// 浮动面板追踪状态
const isTracking = ref(false)
const mouseY = ref(0)

// 图表容器尺寸缓存：只在尺寸变化时读取 DOM，避免每次鼠标移动都强制回流
let _chartRect = { left: 0, top: 0, bottom: 0 }
let _chartRectTs = 0
function _getChartRect(el: HTMLElement) {
  const now = Date.now()
  if (now - _chartRectTs > 200) { // 每 200ms 最多读一次 DOM
    const r = el.getBoundingClientRect()
    _chartRect = { left: r.left, top: r.top, bottom: r.bottom }
    _chartRectTs = now
  }
  return _chartRect
}

const floatPanelStyle = computed(() => {
  if (!chartEl.value) return { display: 'none' as const }
  const rect = _getChartRect(chartEl.value)
  const pw = 130; const ph = 310
  const left = Math.max(2, rect.left - pw - 4)
  let top = mouseY.value - ph / 2
  if (top < rect.top) top = rect.top
  if (top + ph > rect.bottom) top = rect.bottom - ph
  return { position: 'fixed' as const, left: left + 'px', top: top + 'px', zIndex: 9999 }
})

const route = useRoute()
const { keyword, results: searchResults, search } = useStockSearch()
const kline = useKlineData()
const chart = useChart()
const drawingTool = useDrawingTool(chart.instance, kline.klineData)
const drawingBtnRef = useTemplateRef<HTMLElement>('drawingBtnRef')
const store = useAuthStore()
const loginDialogVisible = ref(false)

// 登录成功后刷新收藏状态
const onLoginSuccess = () => {
  loginDialogVisible.value = false
  if (selectedCode.value) {
    _checkWatchlist(selectedCode.value)
  }
}

// 画线面板定位：stock-header 右上角
const drawingPanelStyle = computed(() => {
  if (!stockHeaderEl.value) return { visibility: 'hidden' } as Record<string, string>
  const r = stockHeaderEl.value.getBoundingClientRect()
  return {
    position: 'fixed',
    top: (r.top + 6) + 'px',
    right: (window.innerWidth - r.right + 6) + 'px',
    zIndex: '100',
  } as Record<string, string>
})

// 画图模式下隐藏十字线
watch(() => drawingTool.drawingMode.value, (on) => {
  if (!chart.instance.value) return
  if (on) {
    chart.instance.value.setOption({ axisPointer: { show: false } })
  } else {
    chart.instance.value.setOption({ axisPointer: { show: true, link: [{ xAxisIndex: 'all' }] } })
  }
  // 画线模式切换时同步更新 dataZoom 拖拽行为
  chart.instance.value.setOption({
    dataZoom: [{ moveOnMouseMove: !on }],
  })
})

const selectedCode = shallowRef('')
const showDropdown = shallowRef(false)
const activeIndex = shallowRef(0)
const chartEl = useTemplateRef<HTMLElement>('chartEl')
const searchInputRef = useTemplateRef<HTMLInputElement>('searchInputRef')

const filteredResults = computed(() => {
  const source = keyword.value ? searchResults.value.filter((s: any) => s.code.includes(keyword.value) || s.name.includes(keyword.value)) : searchResults.value
  return source.slice(0, 6)
})

// ── 指标数据：所有字段直接从接口返回的 raw 对象读取，不逐指标 .map() 拷贝 ──
// 仅 VOL_MA5/MA10 接口不返回，需前端计算
function _volMA(values: number[], period: number): (number | null)[] {
  const r: (number | null)[] = []
  let s = 0
  for (let i = 0; i < values.length; i++) {
    s += values[i]
    if (i < period - 1) r.push(null)
    else {
      if (i >= period) s -= values[i - period]
      r.push(s / period)
    }
  }
  return r
}

// ── cursor helpers ──
function atIdx(): number { const raw = kline.klineData.value; const ci = crossIdx.value; return ci >= 0 && ci < raw.length ? ci : raw.length - 1 }

const cursorVol = computed(() => { const raw = kline.klineData.value; const i = atIdx(); return i >= 0 ? raw[i]?.volume : null })
// MACD / KDJ / 均线值：直接从 raw 读取接口返回的预计算字段
const cursorDIF = computed(() => { const raw = kline.klineData.value; const i = atIdx(); return i >= 0 && i < raw.length ? (raw[i].macd_dif ?? null) : null })
const cursorDEA = computed(() => { const raw = kline.klineData.value; const i = atIdx(); return i >= 0 && i < raw.length ? (raw[i].macd_dea ?? null) : null })
const cursorMACD = computed(() => { const raw = kline.klineData.value; const i = atIdx(); return i >= 0 && i < raw.length ? (raw[i].macd_hist ?? null) : null })
const cursorK = computed(() => { const raw = kline.klineData.value; const i = atIdx(); return i >= 0 && i < raw.length ? (raw[i].kdj_k ?? null) : null })
const cursorD = computed(() => { const raw = kline.klineData.value; const i = atIdx(); return i >= 0 && i < raw.length ? (raw[i].kdj_d ?? null) : null })
const cursorJ = computed(() => { const raw = kline.klineData.value; const i = atIdx(); return i >= 0 && i < raw.length ? (raw[i].kdj_j ?? null) : null })
// VOL_MA 不在接口返回字段中，前端计算并缓存
const _volMA5Cache = computed(() => { const raw = kline.klineData.value; if (!raw.length) return [] as (number | null)[]; const r: (number | null)[] = []; let s = 0; for (let i = 0; i < raw.length; i++) { s += Number(raw[i].volume); if (i < 4) { r.push(null) } else { if (i >= 5) s -= Number(raw[i - 5].volume); r.push(s / 5) } } return r })
const _volMA10Cache = computed(() => { const raw = kline.klineData.value; if (!raw.length) return [] as (number | null)[]; const r: (number | null)[] = []; let s = 0; for (let i = 0; i < raw.length; i++) { s += Number(raw[i].volume); if (i < 9) { r.push(null) } else { if (i >= 10) s -= Number(raw[i - 10].volume); r.push(s / 10) } } return r })
const cursorVolMa5 = computed(() => { const arr = _volMA5Cache.value; const i = atIdx(); return i >= 0 && i < arr.length ? arr[i] : null })
const cursorVolMa10 = computed(() => { const arr = _volMA10Cache.value; const i = atIdx(); return i >= 0 && i < arr.length ? arr[i] : null })

const currentBar = computed(() => {
  const raw = kline.klineData.value
  const idx = atIdx()
  return idx >= 0 && idx < raw.length ? raw[idx] : null
})

const currentBarChange = computed(() => {
  if (!currentBar.value) return '—'
  const prev = kline.klineData.value[atIdx() - 1]
  if (!prev) return '—'
  const diff = Number(currentBar.value.close) - Number(prev.close)
  return `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}`
})

const currentBarPriceClass = computed(() => {
  if (!currentBar.value) return ''
  const prev = kline.klineData.value[atIdx() - 1]
  if (!prev) return ''
  return Number(currentBar.value.close) > Number(prev.close) ? 'price-up' : Number(currentBar.value.close) < Number(prev.close) ? 'price-down' : ''
})

const currentBarAmplitude = computed(() => {
  if (!currentBar.value) return '—'
  const high = Number(currentBar.value.high)
  const low = Number(currentBar.value.low)
  const close = Number(currentBar.value.close)
  return close ? `${((high - low) / close * 100).toFixed(2)}%` : '—'
})

const currentBarTurnoverRate = computed(() => {
  if (!currentBar.value) return '—'
  if (currentBar.value.turnoverRate != null) return `${Number(currentBar.value.turnoverRate).toFixed(2)}%`
  if (currentBar.value.turnover_rate != null) return `${Number(currentBar.value.turnover_rate).toFixed(2)}%`
  if (currentBar.value.turnover != null) return `${Number(currentBar.value.turnover).toFixed(2)}%`
  return '—'
})

const currentBarFloatShare = computed(() => {
  if (!currentBar.value) return '—'
  if (currentBar.value.floatShares != null) return formatAmount(Number(currentBar.value.floatShares))
  if (currentBar.value.float_share != null) return formatAmount(Number(currentBar.value.float_share))
  return '—'
})

function fmtVol(v: any) { return v != null ? (Number(v) / 1e4).toFixed(2) + ' 万' : '—' }
function fmtPrice(v: any) { return v != null ? (typeof v === 'number' ? v.toFixed(2) : v) : '—' }
function fmtMACD(v: any) { return v != null ? (typeof v === 'number' ? v.toFixed(3) : v) : '—' }
function fmtKDJ(v: any) { return v != null ? (typeof v === 'number' ? v.toFixed(2) : v) : '—' }

/** 根据当前可见的指标子面板，计算面板标签的 top 位置 */
function getPanelTop(key: string): string {
  const tops: Record<string, number> = { vol: 44, macd: 61, kdj: 78 }
  return `${tops[key] ?? 0}%`
}

function maValue(ma: any): string {
  const raw = kline.klineData.value; if (!raw.length) return '—'
  const r = raw[atIdx()]; const v = r?.['ma' + ma.period]; return v != null ? (v as number).toFixed(2) : '—'
}

// ── 指标菜单 & 编辑器 ──
function onToggleIndicatorMenu() {
  showIndicatorMenu.value = !showIndicatorMenu.value
}
function onSelectMA() {
  activeIndicator.value = 'ma'
  showIndicatorMenu.value = false
  updateMainIndicator()
}
function onOpenMaEditor() {
  maEditorValues.value = maConfigs.value.map(m => ({ period: m.period }))
  showMaEditor.value = true
  showIndicatorMenu.value = false
}
function onConfirmMaEdit() {
  maConfigs.value = maConfigs.value.map((m, i) => {
    const p = Math.max(0, Math.min(500, Math.floor(maEditorValues.value[i].period) || 0))
    return { ...m, period: p, label: 'MA' + p }
  })
  showMaEditor.value = false
  activeIndicator.value = 'ma'
  updateMainIndicator()
}
function onCancelMaEdit() {
  showMaEditor.value = false
}
function onToggleZhixingheyi() {
  activeIndicator.value = 'zhixingheyi'
  showIndicatorMenu.value = false
  updateMainIndicator()
}

/** 更新主图指标系列（切换 MA/知行合一 或编辑 MA 周期后调用） */
function updateMainIndicator() {
  if (!chart.instance.value) return
  const raw = kline.klineData.value; if (!raw.length) return
  const showMA = activeIndicator.value === 'ma'

  // 过滤出非指标系列（K线/VOL/MACD/KDJ 保持不变）
  const indicatorNames = new Set([
    ...maConfigs.value.map(m => m.label),
    'ZXDQ', 'ZXDKX',
  ])
  const opt = chart.instance.value.getOption() as any
  const allSeries = ((opt.series ?? []) as any[]).filter((s: any) => {
    const n = s.name
    if (indicatorNames.has(n)) return false
    if (/^MA\d+$/.test(n)) return false
    if (n === 'ZXDQ' || n === 'ZXDKX') return false
    return true
  })

  // 追加 MA 均线系列 — 直接从 raw 读接口字段
  for (const m of maConfigs.value) {
    const active = showMA && m.period > 0
    allSeries.push({
      name: m.label, type: 'line', xAxisIndex: 0, yAxisIndex: 0,
      data: active ? raw.map((r: any) => r['ma' + m.period] ?? null) : [],
      symbol: 'none',
      lineStyle: { width: 1, color: m.color, opacity: active ? 1 : 0 },
    })
  }

  // 追加 ZXDQ/ZXDKX
  allSeries.push({
    name: 'ZXDQ', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
    data: !showMA ? raw.map((r: any) => r.zxdq ?? null) : [],
    symbol: 'none',
    lineStyle: { width: 1, color: '#FFFFFF', opacity: !showMA ? 1 : 0 },
  })
  allSeries.push({
    name: 'ZXDKX', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
    data: !showMA ? raw.map((r: any) => r.zxdkx ?? null) : [],
    symbol: 'none',
    lineStyle: { width: 1, color: '#FFD700', opacity: !showMA ? 1 : 0 },
  })

  chart.instance.value.setOption({ series: allSeries }, { replaceMerge: ['series'] })
}

function focusChartIndex(index: number) {
  if (!chart.instance.value || !kline.klineData.value.length) return
  chart.instance.value.dispatchAction({ type: 'updateAxisPointer', xAxisIndex: 0, currTrigger: 'manual', dataIndex: index })
  chart.instance.value.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: index })
}

/** DOM mousemove → 追踪鼠标坐标（浮动面板定位） */
function onDomMouseMove(e: MouseEvent) {
  mouseY.value = e.clientY
}
function _onChartMouseLeave() { crossIdx.value = -1 }

function onSearchInput() { showDropdown.value = true; activeIndex.value = 0; search(keyword.value) }

function onSearchKeydown(e: KeyboardEvent) { if (!showDropdown.value) return; const len = filteredResults.value.length; if (!len && e.key !== 'Escape') return; switch (e.key) { case 'ArrowDown': e.preventDefault(); activeIndex.value = (activeIndex.value + 1) % len; break; case 'ArrowUp': e.preventDefault(); activeIndex.value = (activeIndex.value - 1 + len) % len; break; case 'Enter': e.preventDefault(); if (filteredResults.value[activeIndex.value]) selectStock(filteredResults.value[activeIndex.value]); break; case 'Escape': showDropdown.value = false; searchInputRef.value?.blur(); break } }
async function loadMoreOnZoom(params: any) {
   loadingMore = true
   try {
     const oldLen = kline.klineData.value.length
     const added = await kline.loadEarlier()
     if (added > 0) {
       const newLen = kline.klineData.value.length
       const add = newLen - oldLen
       renderChart({
         start: Math.max(0, (params.start / 100 * oldLen + add) / newLen * 100),
         end: Math.min(100, (params.end / 100 * oldLen + add) / newLen * 100),
       })
       drawingTool.onZoom()
     }
   } finally {
     loadingMore = false
   }
 }
async function selectStock(s: any) {
  showDropdown.value = false; activeIndex.value = 0; keyword.value = `${s.code} ${s.name}`
  // 保存旧股票画线
  if (selectedCode.value && store.isLoggedIn()) drawingTool.saveDrawings(selectedCode.value)
  selectedCode.value = s.code
  await kline.selectStock(s.code)
  crossIdx.value = -1
  drawingTool.exitDrawingMode()
  if (store.isLoggedIn()) {
    await drawingTool.loadDrawings(s.code)
  }
  
renderChart()
  drawingTool.onZoom()
  _checkWatchlist(s.code)
}

async function selectStockByCode(code: string) {
  try {
    const res = await stockApi.getByCode(code)
    if (res.data) {
      await selectStock(res.data)
    }
  } catch { /* ignore */ }
}

async function onSwitchPeriod(p: string) { if (!selectedCode.value) return; drawingTool.clearAll(); drawingTool.exitDrawingMode(); await kline.switchPeriod(selectedCode.value, p); crossIdx.value = -1; renderChart() }
async function onToggleAdjusted() { if (!selectedCode.value) return; drawingTool.clearAll(); drawingTool.exitDrawingMode(); kline.toggleAdjusted(); const to = new Date().toISOString().slice(0, 10); const from = kline.loadedFrom.value || new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10); await kline.loadRange(selectedCode.value, from, to, true); crossIdx.value = -1; renderChart() }

function onToggleDrawingMode() {
  if (drawingTool.drawingMode.value) {
    drawingTool.exitDrawingMode()
  } else if (kline.stockInfo.value) {
    drawingTool.enterDrawingMode()
  }
}

// ── 图表 ──
let loadingMore = false

function renderChart(keepZoom?: { start: number; end: number }) {
  const raw = kline.klineData.value; if (!chartEl.value || !raw.length) return

  // 固定 4 面板布局：K线(38%) + VOL(15%) + MACD(15%) + KDJ(14%)
  const grids: any[] = []
  const xAxes: any[] = []
  const yAxes: any[] = []

  grids.push({ left: '10%', right: '8%', top: '2%', height: '38%' })   // K线
  grids.push({ left: '10%', right: '8%', top: '44%', height: '15%' })   // VOL
  grids.push({ left: '10%', right: '8%', top: '61%', height: '15%' })   // MACD
  grids.push({ left: '10%', right: '8%', top: '78%', height: '14%' })   // KDJ

  const ts = raw.map((r: any) => r.ts)
  for (let i = 0; i < grids.length; i++) {
    xAxes.push({ type: 'category' as const, data: ts, gridIndex: i, axisLabel: { show: i === grids.length - 1, color: '#B2B5BE', fontSize: 10 }, axisLine: { lineStyle: { color: '#2B2B43' } }, axisTick: { show: false }, splitLine: { show: false } })
  }
  // K线 Y
  yAxes.push({ scale: true, splitNumber: 5, gridIndex: 0, axisLabel: { color: '#B2B5BE', fontSize: 10, formatter: (v: number) => v.toFixed(2) }, axisLine: { show: false }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.08)' } } })
  // 子面板 Y：仅显示屏幕内最低/最高值
  const subAxisBase = { axisLine: { show: false }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } } }
  // VOL(5,10)
  yAxes.push(Object.assign({
    scale: true, splitNumber: 1, gridIndex: 1,
    axisLabel: { color: '#B2B5BE', fontSize: 9, formatter: (v: number) => v >= 1e8 ? (v/1e8).toFixed(2)+'亿' : (v/1e4).toFixed(0)+'万' },
  }, subAxisBase))
  // MACD(12,26,9)
  yAxes.push(Object.assign({
    scale: true, splitNumber: 1, gridIndex: 2,
    axisLabel: { color: '#B2B5BE', fontSize: 9, formatter: (v: number) => v.toFixed(3) },
  }, subAxisBase))
  // KDJ(9,3,3)
  yAxes.push(Object.assign({
    scale: true, splitNumber: 1, gridIndex: 3,
    axisLabel: { color: '#B2B5BE', fontSize: 9, formatter: (v: number) => v.toFixed(2) },
  }, subAxisBase))

  // ── 蜡烛图数据 ──
  const ohlc = raw.map((r: any, i: number) => {
    const prev = i > 0 ? raw[i - 1].close : raw[i].close
    const up = r.close > prev; const down = r.close < prev
    const c = up ? '#e63535' : down ? '#1aad19' : '#9598A1'
    return { value: [r.open, r.close, r.low, r.high], itemStyle: { color: c, color0: c, borderColor: c, borderColor0: c } }
  })

  const showMA = activeIndicator.value === 'ma'

  const series: any[] = [
    { name: 'K线', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0, data: ohlc, barCategoryGap: '8%', barGap: '0%', barWidth: '85%' },
  ]

  // 面板 0: 均线 — 直接从 raw 读接口预计算字段（不调 _getMA）
  for (const m of maConfigs.value) {
    const active = showMA && m.period > 0
    series.push({
      name: m.label, type: 'line' as const, xAxisIndex: 0, yAxisIndex: 0,
      data: active ? raw.map((r: any) => r['ma' + m.period] ?? null) : [],
      symbol: 'none',
      lineStyle: { width: 1, color: m.color, opacity: active ? 1 : 0 },
    })
  }

  // 面板 0: 知行合一趋势线 — 直接从 raw 读 zxdq/zxdkx
  series.push({
    name: 'ZXDQ', type: 'line' as const, xAxisIndex: 0, yAxisIndex: 0,
    data: !showMA ? raw.map((r: any) => r.zxdq ?? null) : [],
    symbol: 'none',
    lineStyle: { width: 1, color: '#FFFFFF', opacity: !showMA ? 1 : 0 },
  })
  series.push({
    name: 'ZXDKX', type: 'line' as const, xAxisIndex: 0, yAxisIndex: 0,
    data: !showMA ? raw.map((r: any) => r.zxdkx ?? null) : [],
    symbol: 'none',
    lineStyle: { width: 1, color: '#FFD700', opacity: !showMA ? 1 : 0 },
  })

  let gi = 1

  // 面板 1: VOL
  const volData = raw.map((r: any, i: number) => {
    const prev = i > 0 ? raw[i - 1].close : raw[i].close
    const c = r.close > prev ? 'rgba(230,53,53,0.72)' : r.close < prev ? 'rgba(26,173,25,0.72)' : 'rgba(149,152,161,0.30)'
    return { value: r.volume, itemStyle: { color: c } }
  })
  const volValues = raw.map((r: any) => Number(r.volume))
  const volMA5 = _volMA(volValues, 5)
  const volMA10 = _volMA(volValues, 10)
  series.push({ name: '成交量', type: 'bar', xAxisIndex: gi, yAxisIndex: gi, data: volData, barCategoryGap: '8%', barWidth: '85%' })
  series.push({ name: 'VOL_MA5', type: 'line', xAxisIndex: gi, yAxisIndex: gi, data: volMA5, symbol: 'none', lineStyle: { width: 1, color: '#fde047' } })
  series.push({ name: 'VOL_MA10', type: 'line', xAxisIndex: gi, yAxisIndex: gi, data: volMA10, symbol: 'none', lineStyle: { width: 1, color: '#2196f3' } })
  gi++

  // 面板 2: MACD — 直接从 raw 读 macd_dif/dea/hist
  const macdDiffs = raw.map((r: any) => r.macd_dif ?? null)
  const macdDeas = raw.map((r: any) => r.macd_dea ?? null)
  const macdBars = raw.map((r: any) => {
    const v = r.macd_hist
    if (v == null) return null
    return { value: v, itemStyle: { color: v >= 0 ? 'rgba(230,53,53,0.65)' : 'rgba(26,173,25,0.65)' } }
  })
  series.push({ name: 'DIF', type: 'line', xAxisIndex: gi, yAxisIndex: gi, data: macdDiffs, symbol: 'none', lineStyle: { width: 1, color: '#f8fafc' } })
  series.push({ name: 'DEA', type: 'line', xAxisIndex: gi, yAxisIndex: gi, data: macdDeas, symbol: 'none', lineStyle: { width: 1, color: '#fde047' } })
  series.push({ name: 'MACD', type: 'bar', xAxisIndex: gi, yAxisIndex: gi, data: macdBars, barCategoryGap: '8%', barWidth: '85%' })
  gi++

  // 面板 3: KDJ — 直接从 raw 读 kdj_k/d/j
  series.push({ name: 'K', type: 'line', xAxisIndex: gi, yAxisIndex: gi, data: raw.map((r: any) => r.kdj_k ?? null), symbol: 'none', lineStyle: { width: 1, color: '#f8fafc' } })
  series.push({ name: 'D', type: 'line', xAxisIndex: gi, yAxisIndex: gi, data: raw.map((r: any) => r.kdj_d ?? null), symbol: 'none', lineStyle: { width: 1, color: '#fde047' } })
  series.push({ name: 'J', type: 'line', xAxisIndex: gi, yAxisIndex: gi, data: raw.map((r: any) => r.kdj_j ?? null), symbol: 'none', lineStyle: { width: 1, color: '#f472b6' } })
  gi++

  const WINDOW_BARS = 60
  const defaultStart = raw.length <= WINDOW_BARS ? 0 : Math.max(0, 100 - Math.round((WINDOW_BARS / raw.length) * 100))
  const dz = keepZoom ?? { start: defaultStart, end: 100 }
  const allGridIdx = grids.map((_, i) => i)

  if (!chart.instance.value) {
    chart.init(chartEl.value)
    const chartInst = chart.instance.value!
    chartInst.on('datazoom', (params: any) => {
      updateSubAxisRange()
      drawingTool.onZoom()
      if (loadingMore || !kline.hasMore.value || kline.loading.value) return
      // 可视窗口左边缘进入最左 15% 时触发加载更早数据
      const ds = params.start ?? params.batch?.[0]?.start
      const de = params.end ?? params.batch?.[0]?.end
      if (ds == null || ds > 15) return
      loadMoreOnZoom({ start: ds, end: de })
    })
    // 单击主图任意位置 → 切换追踪模式
    chartInst.getZr().on('click', (e: any) => {
      if (drawingTool.drawingMode.value) return
      const rect = chartEl.value!.getBoundingClientRect()
      const relY = (e.event?.clientY ?? e.offsetY) - rect.top
      if (relY < rect.height * 0.02 || relY > rect.height * 0.42) return
      isTracking.value = !isTracking.value
      if (isTracking.value) focusChartIndex(crossIdx.value)
      else crossIdx.value = -1
    })
    // 双击 → 退出追踪模式
    chartInst.getZr().on('dblclick', () => {
      if (drawingTool.drawingMode.value) return
      isTracking.value = false
      crossIdx.value = -1
    })
    // 鼠标离开图表 → 指标回归最新值
    chartEl.value!.addEventListener('mouseleave', _onChartMouseLeave)
    // DOM 层追踪鼠标坐标
    chartEl.value!.addEventListener('mousemove', onDomMouseMove)
    // 画线工具事件
    chartInst.getZr().on('mousedown', (e: any) => drawingTool.handleMouseDown(e))
    chartInst.getZr().on('mousemove', (e: any) => drawingTool.handleMouseMove(e))
    chartInst.getZr().on('mouseup', (e: any) => drawingTool.handleMouseUp(e))
    chartInst.getZr().on('contextmenu', (e: any) => drawingTool.handleContextMenu(e))
  }

  loadingMore = true  // 阻止 render 过程中/后触发的 datazoom 事件加载数据
  chart.setOption({
    animation: false,
    backgroundColor: '#131722', textStyle: { color: '#B2B5BE' },
    // 仅保留十字线，不显示 tooltip 弹框（数据改由浮动面板展示）
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: '#9598A1', type: 'dashed', width: 1 }, label: { show: false } },
      backgroundColor: 'transparent',
      borderColor: 'transparent',
      borderWidth: 0,
      padding: 0,
      shadowBlur: 0,
      shadowColor: 'transparent',
      textStyle: { color: 'transparent', fontSize: 0 },
      formatter: (ps: any) => {
        const k = ps.find((p: any) => p.seriesName === 'K线')
        const idx = k?.dataIndex
        if (idx != null && idx !== crossIdx.value) {
          crossIdx.value = idx
        }
        return ''
      },
      extraCssText: 'pointer-events: none; box-shadow: none;',
    },
    grid: grids, xAxis: xAxes, yAxis: yAxes, series,
    dataZoom: [{
      type: 'inside', xAxisIndex: allGridIdx,
      start: dz.start, end: dz.end,
      minSpan: 5, maxSpan: 80,           // 限制缩放幅度
      zoomOnMouseWheel: 'ctrl',          // Ctrl+滚轮才缩放，避免触控板误触
      moveOnMouseMove: !drawingTool.drawingMode.value, // 画线模式禁止拖拽平移
    }],
  } as any, true)  // notMerge: true — 全量替换 chart option
  // 首次渲染后用可见范围更新附图 Y 轴 min/max
  updateSubAxisRange()
  loadingMore = false
}

/** 根据 dataZoom 当前可见范围，同步 MACD/KDJ 附图 Y 轴的最低/最高值 */
function updateSubAxisRange() {
  if (!chart.instance.value || !kline.klineData.value.length) return
  const raw = kline.klineData.value; const total = raw.length
  const opt = chart.instance.value.getOption() as any
  const dz = opt.dataZoom?.[0]
  if (!dz) return
  const si = Math.max(0, Math.floor((dz.start ?? 0) / 100 * total))
  const ei = Math.min(total, Math.ceil((dz.end ?? 100) / 100 * total))

  // MACD 可见范围 min/max（直接从 raw 读取，不创建中间数组）
  let macdMin = Infinity, macdMax = -Infinity
  for (let i = si; i < ei; i++) {
    const r = raw[i]
    if (r.macd_dif != null) { if (r.macd_dif < macdMin) macdMin = r.macd_dif; if (r.macd_dif > macdMax) macdMax = r.macd_dif }
    if (r.macd_dea != null) { if (r.macd_dea < macdMin) macdMin = r.macd_dea; if (r.macd_dea > macdMax) macdMax = r.macd_dea }
    if (r.macd_hist != null) { if (r.macd_hist < macdMin) macdMin = r.macd_hist; if (r.macd_hist > macdMax) macdMax = r.macd_hist }
  }
  if (!isFinite(macdMin)) { macdMin = -1; macdMax = 1 }
  const macdPad = Math.max((macdMax - macdMin) * 0.20, 0.05)
  macdMin -= macdPad
  macdMax += macdPad

  // KDJ 可见范围 min/max（直接从 raw 读取）
  let kdjMin = Infinity, kdjMax = -Infinity
  for (let i = si; i < ei; i++) {
    const r = raw[i]
    if (r.kdj_k != null) { if (r.kdj_k < kdjMin) kdjMin = r.kdj_k; if (r.kdj_k > kdjMax) kdjMax = r.kdj_k }
    if (r.kdj_d != null) { if (r.kdj_d < kdjMin) kdjMin = r.kdj_d; if (r.kdj_d > kdjMax) kdjMax = r.kdj_d }
    if (r.kdj_j != null) { if (r.kdj_j < kdjMin) kdjMin = r.kdj_j; if (r.kdj_j > kdjMax) kdjMax = r.kdj_j }
  }
  if (!isFinite(kdjMin)) { kdjMin = -10; kdjMax = 110 }

  chart.instance.value.setOption({
    yAxis: [{}, {},
      { min: macdMin, max: macdMax, interval: Math.abs(macdMax - macdMin) || 0.001 },
      { min: kdjMin, max: kdjMax, interval: Math.abs(kdjMax - kdjMin) || 1 }],
  })
}

function onClickOutside(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.search-box')) { showDropdown.value = false; activeIndex.value = 0 }
  // 关闭指标菜单
  if (showIndicatorMenu.value && !(e.target as HTMLElement).closest('.indicator-menu') && !(e.target as HTMLElement).closest('.indicator-btn')) {
    showIndicatorMenu.value = false
  }
  // 关闭画线面板
  if (drawingTool.drawingMode.value && !(e.target as HTMLElement).closest('.drawing-panel') && !(e.target as HTMLElement).closest('.tool-btn')) {
    drawingTool.exitDrawingMode()
  }
}
onMounted(() => {
  document.addEventListener('click', onClickOutside)
  document.addEventListener('keydown', onKeydown)
  const code = route.query.code as string | undefined
  if (code) {
    selectStockByCode(code)
  }
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && drawingTool.drawingMode.value) {
    drawingTool.exitDrawingMode()
  }
}

watch(() => route.query.code, (newCode) => {
  if (newCode && typeof newCode === 'string' && newCode !== selectedCode.value) {
    selectStockByCode(newCode)
  }
})
onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
  document.removeEventListener('keydown', onKeydown)
  if (selectedCode.value && store.isLoggedIn()) drawingTool.saveDrawings(selectedCode.value)
  drawingTool.detach()
  // 移除 DOM 层事件
  if (chartEl.value) {
    chartEl.value.removeEventListener('mouseleave', _onChartMouseLeave)
    chartEl.value.removeEventListener('mousemove', onDomMouseMove)
  }
  // 销毁 ECharts 实例（含 resize listener）
  chart.dispose()
})
</script>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; padding: 8px 14px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-lg); }
.toolbar-right { display: flex; align-items: center; gap: 6px; margin-left: auto; flex-shrink: 0; }
.search-box { position: relative; flex: 1; max-width: 420px; }
.search-box__icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--text-tertiary); display: flex; align-items: center; pointer-events: none; }
.search-box:focus-within .search-box__icon { color: var(--accent); }
.search-box__input { width: 100%; padding: 9px 12px 9px 36px; background: var(--bg-root); border: 1px solid var(--border-default); border-radius: var(--radius-md); color: var(--text-primary); font-size: 13px; font-family: var(--font-sans); outline: none; }
.search-box__input:focus { border-color: var(--accent); box-shadow: var(--shadow-glow); }
.search-box__input::placeholder { color: var(--text-tertiary); }
.search-box__dropdown { position: absolute; top: calc(100% + 6px); left: 0; right: 0; background: var(--bg-overlay); border: 1px solid var(--border-emphasis); border-radius: var(--radius-md); box-shadow: var(--shadow-lg); max-height: 280px; overflow-y: auto; z-index: 50; backdrop-filter: blur(12px); }
.search-box__item { display: flex; align-items: center; gap: 10px; padding: 9px 14px; cursor: pointer; border-bottom: 1px solid var(--border-subtle); }
.search-box__item:last-child { border-bottom: none; }
.search-box__item:hover, .search-box__item--active { background: var(--bg-hover); }
.search-box__item--active { border-left: 2px solid var(--accent); padding-left: 12px; }
.search-box__code { font-family: var(--font-mono); font-size: 13px; font-weight: 500; color: var(--accent); min-width: 68px; }
.search-box__name { font-size: 13px; color: var(--text-primary); flex: 1; }
.search-box__empty { padding: 28px 14px; text-align: center; font-size: 13px; color: var(--text-tertiary); }

.period-switch { display: flex; background: var(--bg-root); border-radius: var(--radius-pill); padding: 2px; gap: 1px; flex-shrink: 0; }
.period-switch__btn { padding: 6px 15px; border: none; border-radius: var(--radius-pill); background: transparent; color: var(--text-secondary); font-size: 12px; font-weight: 500; font-family: var(--font-sans); cursor: pointer; }
.period-switch__btn:hover { color: var(--text-primary); }
.period-switch__btn--active { background: var(--accent); color: #fff; }


.tool-btn { padding: 6px 12px; border: 1px solid var(--border-default); border-radius: var(--radius-pill); background: var(--bg-root); color: var(--text-secondary); font-size: 12px; font-weight: 500; font-family: var(--font-sans); cursor: pointer; flex-shrink: 0; opacity: 0.6; }
.tool-btn:hover { color: var(--text-primary); border-color: var(--accent); opacity: 1; }
.tool-btn--active { background: var(--accent); color: #fff; border-color: var(--accent); opacity: 1; }
.tool-btn:disabled { opacity: 0.3; pointer-events: none; }
.adj-toggle { padding: 6px 12px; border: 1px solid var(--border-default); border-radius: var(--radius-pill); background: var(--bg-root); color: var(--text-secondary); font-size: 12px; font-weight: 500; font-family: var(--font-sans); cursor: pointer; flex-shrink: 0; }
.adj-toggle:hover { color: var(--text-primary); border-color: var(--accent); }
.adj-toggle--on { background: var(--accent); color: #fff; border-color: var(--accent); }

.stock-header { padding: 12px 18px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-lg); margin-bottom: 8px; }
.stock-header__row1 { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.stock-header__name { font-size: 18px; font-weight: 700; color: var(--text-primary); }
.stock-header__code { font-family: var(--font-mono); font-size: 12px; color: var(--text-tertiary); }
.watchlist-btn { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border: 1px solid transparent; border-radius: 50%; background: transparent; color: var(--text-tertiary); cursor: pointer; margin-left: 10px; transition: all 0.2s; position: relative; top: 2px; }
.watchlist-btn:hover { color: #f59e0b; background: rgba(245,158,11,0.08); }
.watchlist-btn--added { color: #f59e0b; border-color: transparent; }
.watchlist-btn--busy { opacity: 0.5; pointer-events: none; }
.stock-header__row2 { display: flex; align-items: center; gap: 20px; }
.stock-header__price-section { display: flex; align-items: baseline; gap: 8px; }
.stock-header__price { font-family: var(--font-mono); font-size: 24px; font-weight: 700; color: var(--text-primary); }
.stock-header__price.price-up { color: #e63535; } .stock-header__price.price-down { color: #1aad19; }
.stock-header__change { font-family: var(--font-mono); font-size: 13px; font-weight: 600; padding: 2px 7px; border-radius: var(--radius-pill); }
.stock-header__change.price-up { color: #e63535; background: rgba(230,53,53,0.12); }
.stock-header__change.price-down { color: #1aad19; background: rgba(26,173,25,0.12); }
.stock-header__change-pct { font-family: var(--font-mono); font-size: 12px; font-weight: 500; }
.stock-header__change-pct.price-up { color: #e63535; } .stock-header__change-pct.price-down { color: #1aad19; }
.stock-header__meta { display: flex; align-items: center; gap: 20px; margin-left: auto; }
.stock-header__meta-item { display: flex; flex-direction: column; gap: 1px; }
.stock-header__meta-label { font-size: 10px; color: var(--text-tertiary); font-weight: 500; }
.stock-header__meta-value { font-family: var(--font-mono); font-size: 13px; font-weight: 600; color: var(--text-primary); }

.chart-section { position: relative; background: #131722; border: 1px solid #2B2B43; border-radius: var(--radius-lg); padding: 6px 4px 2px; }
.chart-section__box { height: 640px; }

.float-panel { min-width: 130px; padding: 6px 8px; background: rgba(19,23,34,0.96); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; backdrop-filter: blur(16px); box-shadow: 0 8px 24px rgba(0,0,0,0.25); pointer-events: none; }
.float-panel__row { display: flex; justify-content: space-between; align-items: center; gap: 6px; padding: 2px 0; font-size: 10px; color: #B2B5BE; }
.float-panel__row strong { color: #F8FAFC; font-weight: 600; font-size: 10px; }

.ma-tags { position: absolute; top: 10px; left: 10.5%; right: 26%; display: flex; align-items: center; gap: 0; z-index: 10; pointer-events: none; font-family: var(--font-mono); font-size: 10px; }
.ma-tags__sep { color: rgba(178,181,190,0.20); pointer-events: none; margin: 0 7px; }
.ma-tag { cursor: pointer; pointer-events: auto; padding: 1px 5px; border-radius: 2px; white-space: nowrap; }
.ma-tag:hover { background: rgba(255,255,255,0.06); }
.ma-tag__input { width: 38px; padding: 1px 3px; border: 1px solid var(--accent); border-radius: 2px; background: #131722; color: var(--text-primary); font-family: var(--font-mono); font-size: 10px; text-align: center; outline: none; }

/* 倒三角按钮 */
.indicator-btn { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; cursor: pointer; pointer-events: auto; color: #9598A1; border-radius: 3px; }
.indicator-btn:hover { color: #F8FAFC; background: rgba(255,255,255,0.08); }

/* 指标下拉菜单（定位在 stock-header 下方） */
.indicator-menu { min-width: 200px; background: #1a1e2e; border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; box-shadow: 0 12px 32px rgba(0,0,0,0.55); padding: 6px; }
.indicator-menu__item { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; color: #B2B5BE; font-family: var(--font-sans); }
.indicator-menu__item:hover { background: rgba(255,255,255,0.06); color: #F8FAFC; }
.indicator-menu__item--active { color: #FFD700; background: rgba(255,215,0,0.06); }
.indicator-menu__edit { margin-left: auto; display: flex; align-items: center; padding: 4px; border-radius: 4px; color: #9598A1; }
.indicator-menu__edit:hover { color: #F8FAFC; background: rgba(255,255,255,0.10); }
.indicator-menu__check { font-size: 11px; color: #FFD700; margin-left: auto; }

/* MA 编辑器弹窗 */
.ma-editor-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.45); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.ma-editor { background: #1a1e2e; border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; padding: 20px 24px; min-width: 240px; box-shadow: 0 12px 32px rgba(0,0,0,0.45); }
.ma-editor__title { font-size: 14px; font-weight: 600; color: #F8FAFC; margin-bottom: 14px; }
.ma-editor__row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.ma-editor__dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.ma-editor__label { font-family: var(--font-mono); font-size: 12px; color: #B2B5BE; min-width: 42px; }
.ma-editor__input { width: 56px; padding: 4px 8px; border: 1px solid rgba(255,255,255,0.12); border-radius: 4px; background: #131722; color: #F8FAFC; font-family: var(--font-mono); font-size: 12px; text-align: center; outline: none; }
.ma-editor__input:focus { border-color: var(--accent); box-shadow: var(--shadow-glow); }
.ma-editor__unit { font-size: 11px; color: #9598A1; }
.ma-editor__hint { font-size: 11px; color: #9598A1; margin: 8px 0 16px; }
.ma-editor__actions { display: flex; justify-content: flex-end; gap: 8px; }
.ma-editor__btn { padding: 6px 18px; border-radius: 6px; font-size: 12px; font-weight: 500; font-family: var(--font-sans); cursor: pointer; border: none; }
.ma-editor__btn--cancel { background: rgba(255,255,255,0.06); color: #B2B5BE; }
.ma-editor__btn--cancel:hover { background: rgba(255,255,255,0.10); color: #F8FAFC; }
.ma-editor__btn--confirm { background: var(--accent); color: #fff; }
.ma-editor__btn--confirm:hover { opacity: 0.85; }

.panel-labels { position: absolute; top: 0; left: 10.5%; right: 8%; bottom: 0; z-index: 10; pointer-events: none; font-family: var(--font-mono); font-size: 9px; }
.panel-label { position: absolute; left: 0; right: 0; display: flex; align-items: center; gap: 10px; white-space: nowrap; padding: 2px 8px; }
.panel-label__arrow { font-size: 7px; color: var(--text-tertiary); cursor: pointer; pointer-events: auto; }
.panel-label__arrow:hover { color: var(--text-primary); }
.panel-label__name { color: #9598A1; font-weight: 500; }
.panel-label__val { color: rgba(178,181,190,0.7); }
.panel-label__val b { font-weight: 600; }
.c-up { color: #e63535 !important; } .c-down { color: #1aad19 !important; }
.c-dif { color: #f8fafc; } .c-dea { color: #fde047; }
.c-k { color: #f8fafc; } .c-d { color: #fde047; } .c-j { color: #f472b6; }
.c-ma5 { color: #fde047; } .c-ma10 { color: #2196f3; }

.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 100px 20px; text-align: center; }
.empty-state__mark { font-size: 56px; color: var(--text-tertiary); opacity: 0.3; margin-bottom: 20px; }
.empty-state__title { font-size: 18px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.empty-state__desc { font-size: 14px; color: var(--text-tertiary); }

</style>
