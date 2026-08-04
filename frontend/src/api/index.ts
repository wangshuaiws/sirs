import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

// 请求级自定义标记（axios 允许自定义字段，这里补齐类型）
declare module 'axios' {
  export interface AxiosRequestConfig {
    meta?: { silentAuth?: boolean }
  }
}

const http = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

// 请求拦截：自动带 token
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：统一错误处理
http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body.code !== 0) {
      if (body.code === 1003) {
        // 未登录 / Token 过期：清除无效凭证（isLoggedIn 立即变 false），不弹通用 toast。
        // 查询类请求（meta.silentAuth）静默降级；主动操作触发全局 auth-expired 事件由 App 弹登录框。
        useAuthStore().clearAuth()
        if (!(res.config as any).meta?.silentAuth) {
          window.dispatchEvent(new Event('auth-expired'))
        }
        return Promise.reject(body)
      }
      ElMessage.error(body.msg || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  (err) => {
    ElMessage.error('网络错误，请稍后重试')
    return Promise.reject(err)
  },
)

// ── 认证 ──
export const authApi = {
  captcha: () => http.get('/auth/captcha'),
  register: (data: { username: string; password: string; captchaId: string; captchaCode: string }) =>
    http.post('/auth/register', data),
  login: (data: { username: string; password: string; captchaId: string; captchaCode: string }) =>
    http.post('/auth/login', data),
}

// ── 股票 ──
export const stockApi = {
  search: (keyword: string) => http.get('/stocks/search', { params: { keyword } }),
  getByCode: (code: string) => http.get(`/stocks/${code}`),
}

// ── K线 ──
export const klineApi = {
  get: (code: string, period = 'daily', from?: string, to?: string, adjusted = true) =>
    http.get(`/kline/${code}`, { params: { period, from, to, adjusted } }),
}

// ── 分组 ──
export const groupApi = {
  list: () => http.get('/groups'),
  create: (data: { name: string; description?: string }) => http.post('/groups', data),
  update: (id: number, data: { name: string; description?: string }) =>
    http.put(`/groups/${id}`, data),
  delete: (id: number) => http.delete(`/groups/${id}`),
  getStocks: (id: number, code: string, page = 1, size = 10) =>
    http.get(`/groups/${id}/stocks`, { params: { code, page, size } }),
  addStock: (id: number, code: string) => http.post(`/groups/${id}/stocks`, { code }),
  removeStock: (id: number, code: string) => http.delete(`/groups/${id}/stocks/${code}`),
  checkWatchlist: (code: string) => http.get(`/groups/watchlist/${code}`, { meta: { silentAuth: true } }),
}

// ── 通知 ──
export const notificationApi = {
  list: (params: Record<string, any>) =>
    http.get('/notifications', { params }),
  stats: () =>
    http.get('/notifications/stats'),
  markRead: (id: number) =>
    http.put(`/notifications/${id}/read`),
  markAllRead: () =>
    http.put('/notifications/read-all'),
}

// ── 画线工具（K线页查询/保存，未登录或过期静默降级，不弹登录框） ──
export const drawingApi = {
  get: (stockCode: string) => http.get(`/drawings/${stockCode}`, { meta: { silentAuth: true } }),
  save: (stockCode: string, drawings: any[]) => http.put(`/drawings/${stockCode}`, drawings, { meta: { silentAuth: true } }),
  delete: (stockCode: string) => http.delete(`/drawings/${stockCode}`, { meta: { silentAuth: true } }),
}
