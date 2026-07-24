/**
 * 纯工具函数 — 格式化 + 技术指标计算
 */

export function formatVolume(v: number): string {
  if (!v) return '0'
  return (v / 1e4).toFixed(2) + ' 万'
}

export function formatAmount(v: number): string {
  if (!v) return '0'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + ' 亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + ' 万'
  return v.toFixed(0)
}

// ── MA / EMA ──

export function calcMA(data: any[], n: number): (number | null)[] {
  const closes = data.map((d: any) => Number(d.close) || 0)
  const result: (number | null)[] = []
  for (let i = 0; i < closes.length; i++) {
    if (i < n - 1) { result.push(null); continue }
    let sum = 0
    for (let j = i - n + 1; j <= i; j++) sum += closes[j]
    result.push(+(sum / n).toFixed(2))
  }
  return result
}

/** 计算 EMA 数组，前 N-1 个值为 null。与通达信对齐：首日收盘价初始化，递归不截断精度 */
function emaOf(arr: number[], n: number): (number | null)[] {
  const k = 2 / (n + 1)
  const result: (number | null)[] = new Array(arr.length).fill(null)
  for (let i = 0; i < arr.length; i++) {
    if (i < n - 1) continue
    if (i === n - 1) {
      result[i] = arr[i] // 通达信：首日收盘价作为初始 EMA
    } else {
      result[i] = arr[i] * k + result[i - 1]! * (1 - k) // 全程不截断
    }
  }
  return result
}

/** 计算 EMA（从 K 线数据提取收盘价） */
export function calcEMA(data: any[], n: number): (number | null)[] {
  const closes = data.map((d: any) => Number(d.close) || 0)
  return emaOf(closes, n)
}

// ── 知行合一趋势线 ──

/** ZXDQ: EMA(EMA(C,10),10)，白色 */
export function calcZXDQ(data: any[]): (number | null)[] {
  const closes = data.map((d: any) => Number(d.close) || 0)
  const ema10 = emaOf(closes, 10)
  // 在有效 EMA 值上再算一次 EMA10
  const vals: number[] = []
  const idxs: number[] = []
  for (let i = 0; i < ema10.length; i++) {
    if (ema10[i] != null) { vals.push(ema10[i]!); idxs.push(i) }
  }
  const ema2 = emaOf(vals, 10)
  const result: (number | null)[] = new Array(data.length).fill(null)
  for (let j = 0; j < idxs.length; j++) {
    if (ema2[j] != null) result[idxs[j]] = +ema2[j]!.toFixed(2)
  }
  return result
}

/** ZXDKX: (MA(C,14)+MA(C,28)+MA(C,57)+MA(C,114))/4，黄色 */
export function calcZXDKX(data: any[]): (number | null)[] {
  const m14 = calcMA(data, 14)
  const m28 = calcMA(data, 28)
  const m57 = calcMA(data, 57)
  const m114 = calcMA(data, 114)
  const result: (number | null)[] = new Array(data.length).fill(null)
  for (let i = 0; i < data.length; i++) {
    if (m14[i] != null && m28[i] != null && m57[i] != null && m114[i] != null) {
      result[i] = +((m14[i]! + m28[i]! + m57[i]! + m114[i]!) / 4).toFixed(2)
    }
  }
  return result
}

// ── KDJ(9,3,3) ──

export function calcKDJ(data: any[], n = 9, m1 = 3, m2 = 3) {
  const closes = data.map((d: any) => Number(d.close) || 0)
  const highs = data.map((d: any) => Number(d.high) || 0)
  const lows = data.map((d: any) => Number(d.low) || 0)
  const len = data.length

  const k: (number | null)[] = []
  const d: (number | null)[] = []
  const j: (number | null)[] = []

  for (let i = 0; i < len; i++) {
    if (i < n - 1) { k.push(null); d.push(null); j.push(null); continue }

    const start = i - n + 1
    const hMax = Math.max(...highs.slice(start, i + 1))
    const lMin = Math.min(...lows.slice(start, i + 1))
    const rsv = hMax === lMin ? 50 : ((closes[i] - lMin) / (hMax - lMin)) * 100

    const prevK = i === n - 1 ? 50 : (k[i - 1] ?? 50)
    const prevD = i === n - 1 ? 50 : (d[i - 1] ?? 50)

    const curK = (2 / m1) * prevK + (1 / m1) * rsv
    const curD = (2 / m2) * prevD + (1 / m2) * curK
    const curJ = 3 * curK - 2 * curD

    k.push(+curK.toFixed(2))
    d.push(+curD.toFixed(2))
    j.push(+curJ.toFixed(2))
  }

  return { k, d, j }
}

// ── MACD(12,26,9) ──

export function calcMACD(data: any[], fast = 12, slow = 26, signal = 9) {
  const len = data.length
  const closes = data.map((d: any) => Number(d.close) || 0)

  const emaFast = emaOf(closes, fast)
  const emaSlow = emaOf(closes, slow)

  // DIF = EMA12 - EMA26
  const dif: (number | null)[] = new Array(len).fill(null)
  for (let i = 0; i < len; i++) {
    if (emaFast[i] != null && emaSlow[i] != null) {
      dif[i] = +(emaFast[i]! - emaSlow[i]!).toFixed(4)
    }
  }

  // DEA = EMA9 of DIF — 在连续的 dif 值上计算
  const difPairs: { idx: number; val: number }[] = []
  for (let i = 0; i < len; i++) {
    if (dif[i] != null) difPairs.push({ idx: i, val: dif[i]! })
  }

  const deaVals = emaOf(
    difPairs.map((p) => p.val),
    signal,
  )

  const dea: (number | null)[] = new Array(len).fill(null)
  const macd: (number | null)[] = new Array(len).fill(null)

  for (let j = 0; j < difPairs.length; j++) {
    const idx = difPairs[j].idx
    if (deaVals[j] != null) {
      dea[idx] = +deaVals[j]!.toFixed(4)
      macd[idx] = +((dif[idx]! - dea[idx]!) * 2).toFixed(4)
    }
  }

  return { dif, dea, macd }
}
