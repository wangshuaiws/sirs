/**
 * 跨页面股票导航缓存
 *
 * 分组管理列表 / 通知列表 跳转到 K线图前，将当前列表的股票代码写入此缓存。
 * K线图读取缓存获取当前股票的前后邻居，实现左右箭头切换。
 *
 * 模块级变量（非 reactive），SPA 路由切换时持久保存。
 */

let _codes: string[] = []

/** 缓存一组有序股票代码 */
export function setStockCodes(codes: string[]) {
  _codes = codes
}

/** 获取当前股票的前一个和后一个 code，没有返回 null */
export function getNeighbors(code: string): { prev: string | null; next: string | null } {
  if (!_codes.length) return { prev: null, next: null }
  const idx = _codes.indexOf(code)
  if (idx === -1) return { prev: null, next: null }
  return {
    prev: idx > 0 ? _codes[idx - 1] : null,
    next: idx < _codes.length - 1 ? _codes[idx + 1] : null,
  }
}
