import { shallowRef } from 'vue'
import { notificationApi } from '../api'
import type { NotificationItem, NotificationStats } from '../types/notification'

export const TAB_TYPE_MAP: Record<string, string | undefined> = {
  all: undefined,
  golden_cross: 'GOLDEN_CROSS',
  white_line_buy: 'WHITE_LINE_BUY',
  yellow_line_buy: 'YELLOW_LINE_BUY',
  clear_position: 'CLEAR_POSITION',
  re_attention: 'RE_ATTENTION',
}

/** tab key → stats 中的 unread 字段名 */
export const UNREAD_KEY_MAP: Record<string, keyof NotificationStats> = {
  all: 'unreadTotal',
  golden_cross: 'goldenCrossUnread',
  white_line_buy: 'whiteLineBuyUnread',
  yellow_line_buy: 'yellowLineBuyUnread',
  clear_position: 'clearPositionUnread',
  re_attention: 'reAttentionUnread',
}

export const TYPE_LABEL: Record<string, string> = {
  GOLDEN_CROSS: '金叉',
  WHITE_LINE_BUY: '白线买入',
  YELLOW_LINE_BUY: '黄线买入',
  CLEAR_POSITION: '清仓',
  RE_ATTENTION: '再次关注',
}

export const TABS = [
  { key: 'all', label: '全部通知', icon: '◈' },
  { key: 'golden_cross', label: '金叉', icon: '◇' },
  { key: 'white_line_buy', label: '白线买入', icon: '○' },
  { key: 'yellow_line_buy', label: '黄线买入', icon: '◎' },
  { key: 'clear_position', label: '清仓', icon: '◉' },
  { key: 're_attention', label: '再次关注', icon: '◬' },
]

function emptyStats(): NotificationStats {
  return {
    total: 0, unreadTotal: 0,
    goldenCross: 0, goldenCrossUnread: 0,
    whiteLineBuy: 0, whiteLineBuyUnread: 0,
    yellowLineBuy: 0, yellowLineBuyUnread: 0,
    clearPosition: 0, clearPositionUnread: 0,
    reAttention: 0, reAttentionUnread: 0,
  }
}

export function useNotifications() {
  const notifications = shallowRef<NotificationItem[]>([])
  const stats = shallowRef<NotificationStats>(emptyStats())
  const total = shallowRef(0)
  const page = shallowRef(1)
  const pageSize = shallowRef(10)
  const loading = shallowRef(false)
  const activeTab = shallowRef('all')
  const keyword = shallowRef('')
  const dateFrom = shallowRef('')
  const dateTo = shallowRef('')

  async function loadList() {
    loading.value = true
    try {
      const res: any = await notificationApi.list({
        type: TAB_TYPE_MAP[activeTab.value],
        keyword: keyword.value || undefined,
        dateFrom: dateFrom.value || undefined,
        dateTo: dateTo.value || undefined,
        page: page.value,
        size: pageSize.value,
      })
      notifications.value = res.data.records || []
      total.value = res.data.total || 0
    } catch (error) {
      console.error('加载通知列表失败:', error)
      notifications.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  async function loadStats() {
    try {
      const res: any = await notificationApi.stats()
      if (res.data) {
        stats.value = res.data as NotificationStats
      }
    } catch (error) {
      console.error('加载通知统计失败:', error)
      stats.value = emptyStats()
    }
  }

  function switchTab(tab: string) {
    activeTab.value = tab
    page.value = 1
    loadList()
  }

  function onSearch() {
    page.value = 1
    loadList()
  }

  function onPageChange(p: number) {
    page.value = p
    loadList()
  }

  async function markAsRead(id: number) {
    try {
      await notificationApi.markRead(id)
      await loadList()
      await loadStats()
    } catch { /* */ }
  }

  async function markAllAsRead() {
    try {
      await notificationApi.markAllRead()
      await loadList()
      await loadStats()
    } catch { /* */ }
  }

  /** 获取指定 tab 的未读数（最多 99+） */
  function unreadFor(key: string): number {
    const field = UNREAD_KEY_MAP[key]
    if (!field) return 0
    return (stats.value as any)[field] || 0
  }

  return {
    notifications, stats, total, page, pageSize, loading,
    activeTab, keyword, dateFrom, dateTo,
    loadList, loadStats, switchTab, onSearch, onPageChange,
    markAsRead, markAllAsRead, unreadFor,
  }
}
