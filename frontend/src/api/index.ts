import axios from 'axios'
import { ElMessage } from 'element-plus'

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
  login: (data: { username: string; password: string }) =>
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
  getStocks: (id: number) => http.get(`/groups/${id}/stocks`),
  addStock: (id: number, code: string) => http.post(`/groups/${id}/stocks`, { code }),
  removeStock: (id: number, code: string) => http.delete(`/groups/${id}/stocks/${code}`),
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

// ── 画线工具 ──
export const drawingApi = {
  get: (stockCode: string) => http.get(`/drawings/${stockCode}`),
  save: (stockCode: string, drawings: any[]) => http.put(`/drawings/${stockCode}`, drawings),
  delete: (stockCode: string) => http.delete(`/drawings/${stockCode}`),
}
