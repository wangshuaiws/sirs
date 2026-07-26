import { shallowRef, computed } from 'vue'
import { klineApi, stockApi } from '../api'

export function useKlineData() {
  const stockInfo = shallowRef<any>(null)
  const klineData = shallowRef<any[]>([])
  const period = shallowRef('daily')
  const adjusted = shallowRef(true)
  const loading = shallowRef(false)
  const hasMore = shallowRef(true)
  const loadedFrom = shallowRef('')
  const loadedTo = shallowRef('')

  const latestPrice = computed(() => {
    if (!klineData.value.length) return null
    return klineData.value[klineData.value.length - 1]
  })

  const prevClose = computed(() => {
    if (klineData.value.length < 2) return null
    return klineData.value[klineData.value.length - 2]?.close
  })

  const priceChange = computed(() => {
    if (!latestPrice.value || !prevClose.value) return 0
    return (latestPrice.value.close as number) - (prevClose.value as number)
  })

  const priceChangePct = computed(() => {
    if (!prevClose.value || prevClose.value === 0) return '0.00'
    return ((priceChange.value / (prevClose.value as number)) * 100).toFixed(2)
  })

  const priceChangeClass = computed(() => {
    if (priceChange.value > 0) return 'price-up'
    if (priceChange.value < 0) return 'price-down'
    return ''
  })

  /** 聚合加载，按 ts 去重后合并到 klineData。replace=true 时先清空旧数据再加载 */
  async function loadRange(code: string, from: string, to: string, replace = false) {
    loading.value = true
    try {
      const res = await klineApi.get(code, period.value, from, to, adjusted.value)
      const newData: any[] = res.data || []

      if (newData.length === 0) {
        hasMore.value = false
        return 0
      }

      // 去重合并（replace 模式跳过去重，直接替换）
      const existing = replace ? new Set<string>() : new Set(klineData.value.map((d: any) => d.ts))
      const unique = newData.filter((d: any) => !existing.has(d.ts))

      if (unique.length === 0) return 0

      // 按时间排序（replace 模式直接替换）
      klineData.value = replace
        ? unique.sort((a: any, b: any) => a.ts.localeCompare(b.ts))
        : [...unique, ...klineData.value].sort((a: any, b: any) => a.ts.localeCompare(b.ts))

      // 更新已加载范围
      const all = klineData.value
      loadedFrom.value = all[0].ts
      loadedTo.value = all[all.length - 1].ts

      // 返回的数据太少说明已到边界
      if (unique.length < 100) {
        hasMore.value = false
      }

      return unique.length
    } finally {
      loading.value = false
    }
  }

  /** 首次选股：只加载最近 1 年 */
  async function selectStock(code: string) {
    // 清空
    klineData.value = []
    hasMore.value = true
    loadedFrom.value = ''
    loadedTo.value = ''

    const res = await stockApi.getByCode(code)
    stockInfo.value = res.data

    const to = new Date().toISOString().slice(0, 10)
    const from = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
    await loadRange(code, from, to)
  }

  /** 加载更早的历史数据（向更早方向取一年），返回新增条数 */
  async function loadEarlier(): Promise<number> {
    if (!hasMore.value || loading.value || !stockInfo.value) return 0
    const to = loadedFrom.value
    if (!to) return 0
    const from = new Date(
      new Date(to).getTime() - 365 * 24 * 60 * 60 * 1000,
    ).toISOString().slice(0, 10)
    return await loadRange(stockInfo.value.code, from, to)
  }

  /** 切换周期：清空后重新加载。日K 1年，周K/月K 适量加载，更多历史通过 loadEarlier 增量获取 */
  async function switchPeriod(code: string, p: string) {
    period.value = p
    klineData.value = []
    hasMore.value = true
    loadedFrom.value = ''
    loadedTo.value = ''

    const to = new Date().toISOString().slice(0, 10)
    // 日K 1年~250条, 周K 2年~104条, 月K 5年~60条（够了，更多历史滚动左边缘自动加载）
    const years = p === 'monthly' ? 5 : p === 'weekly' ? 2 : 1
    const from = new Date(Date.now() - years * 365 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
    await loadRange(code, from, to)
  }

  /** 切换复权模式：清空后重新加载 */
  function toggleAdjusted() {
    adjusted.value = !adjusted.value
  }

  return {
    stockInfo, klineData, period, adjusted, loading, hasMore, loadedFrom, loadedTo,
    latestPrice, priceChange, priceChangePct, priceChangeClass,
    selectStock, switchPeriod, loadEarlier, loadRange, toggleAdjusted,
  }
}
