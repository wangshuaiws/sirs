export type NotificationType =
  | 'GOLDEN_CROSS'
  | 'WHITE_LINE_BUY'
  | 'YELLOW_LINE_BUY'
  | 'CLEAR_POSITION'
  | 'RE_ATTENTION'

export interface NotificationItem {
  id: number
  userId: number
  stockCode: string
  stockName: string
  type: NotificationType
  message: string
  detail: Record<string, unknown> | null
  isRead: boolean
  createdAt: string
}

export interface NotificationStats {
  total: number
  unreadTotal: number
  goldenCross: number
  goldenCrossUnread: number
  whiteLineBuy: number
  whiteLineBuyUnread: number
  yellowLineBuy: number
  yellowLineBuyUnread: number
  clearPosition: number
  clearPositionUnread: number
  reAttention: number
  reAttentionUnread: number
}

export interface PageResult<T> {
  records: T[]
  total: number
  page: number
  size: number
}

export interface NotificationQuery {
  type?: string
  keyword?: string
  dateFrom?: string
  dateTo?: string
  page: number
  size: number
}
