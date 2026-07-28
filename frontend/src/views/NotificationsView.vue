<script setup lang="ts">
import { computed, shallowRef, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useNotifications, TABS, TYPE_LABEL } from '../composables/useNotifications'
import { useStockSearch } from '../composables/useGroupManager'
import { useAuthStore } from '../stores/auth'
import { setStockCodes } from '../composables/useStockNavigation'
import LoginDialog from '../components/LoginDialog.vue'

const router = useRouter()
const vm = useNotifications()
const { keyword: searchKeyword, results: searchResults, search: doSearch } = useStockSearch()
const store = useAuthStore()
const loginDialogVisible = ref(false)

function goToKline(code: string, name: string) {
  // 缓存当前通知列表的去重股票代码，用于 K线图左右箭头导航
  const codes = [...new Set(vm.notifications.value.map((n: any) => n.stockCode))]
  setStockCodes(codes)
  router.push({ name: 'Kline', query: { code } })
}
const loginDialog = ref<InstanceType<typeof LoginDialog> | null>(null)

// 登录成功后回调
const onLoginSuccess = () => {
  // 刷新通知数据
  vm.loadList()
  vm.loadStats()
}

// 日期选择器 ref — 用于 showPicker()
const dateFromRef = ref<HTMLInputElement | null>(null)
const dateToRef = ref<HTMLInputElement | null>(null)

function openDatePicker(refKey: 'from' | 'to') {
  const el = refKey === 'from' ? dateFromRef.value : dateToRef.value
  if (!el) return
  try {
    el.showPicker()
  } catch {
    el.focus()
    el.click()
  }
}

// 搜索下拉
const showDropdown = shallowRef(false)
const activeIndex = shallowRef(0)

const filteredResults = computed(() => {
  const kw = searchKeyword.value
  if (!kw) return searchResults.value.slice(0, 6)
  return searchResults.value.filter(
    (s: any) => s.code.includes(kw) || s.name.includes(kw),
  ).slice(0, 6)
})

// 监听输入变化自动触发搜索
watch(searchKeyword, (kw) => {
  if (kw) doSearch(kw)
  else searchResults.value = []
  showDropdown.value = true
  activeIndex.value = 0
})

function onSearchKeydown(e: KeyboardEvent) {
  if (!showDropdown.value) return
  const len = filteredResults.value.length
  if (!len && e.key !== 'Escape') return
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      activeIndex.value = (activeIndex.value + 1) % len
      break
    case 'ArrowUp':
      e.preventDefault()
      activeIndex.value = (activeIndex.value - 1 + len) % len
      break
    case 'Enter':
      e.preventDefault()
      if (filteredResults.value[activeIndex.value]) {
        selectStock(filteredResults.value[activeIndex.value])
      } else {
        vm.onSearch()
      }
      break
    case 'Escape':
      showDropdown.value = false
      break
  }
}

function selectStock(s: any) {
  showDropdown.value = false
  activeIndex.value = 0
  searchKeyword.value = `${s.code} ${s.name}`
  vm.keyword.value = s.code
  vm.onSearch()
}

function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.search-box')) {
    showDropdown.value = false
  }
}

function formatTime(ts: string): string {
  if (!ts) return '-'
  return ts.substring(0, 10)
}

function unreadBadge(key: string): string {
  const n = vm.unreadFor(key)
  if (n <= 0) return ''
  return n > 99 ? '99+' : String(n)
}

onMounted(async () => {
  document.addEventListener('click', onDocClick)
  if (!store.isLoggedIn()) {
    return // 未登录由 App.vue 导航守卫拦截，不加载数据
  }
  await Promise.all([vm.loadList(), vm.loadStats()])
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})
</script>

<template>
  <div class="notifications-page">
    <div class="notifications-layout">
      <!-- 左侧边栏 -->
      <aside class="notify-sidebar">
        <div class="notify-sidebar__head">
          <h3 class="notify-sidebar__title">通知中心</h3>
          <button
            class="btn-primary notify-sidebar__read-all-btn"
            @click="vm.markAllAsRead()"
          >全部已读</button>
        </div>
        <div class="notify-sidebar__list">
          <div
            v-for="tab in TABS"
            :key="tab.key"
            class="notify-sidebar__item"
            :class="{ 'notify-sidebar__item--active': vm.activeTab.value === tab.key }"
            @click="vm.switchTab(tab.key)"
          >
            <span class="notify-sidebar__bar"></span>
            <span class="notify-sidebar__icon">{{ tab.icon }}</span>
            <span class="notify-sidebar__label">{{ tab.label }}</span>
            <span
              class="notify-sidebar__badge"
              v-if="unreadBadge(tab.key)"
            >{{ unreadBadge(tab.key) }}</span>
          </div>
        </div>
      </aside>

      <!-- 右侧面板（复用分组管理样式） -->
      <section class="stock-panel">
        <div class="stock-panel__head" style="display:flex;align-items:center;gap:12px;flex-shrink:0">
          <div class="search-box" style="width:240px;flex-shrink:0">
            <span class="search-box__icon">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            </span>
            <input v-model="searchKeyword" @keydown="onSearchKeydown" type="text" class="search-box__input" placeholder="搜索代码或名称" />
            <div class="search-box__dropdown" v-if="showDropdown && (filteredResults.length || searchKeyword)">
              <template v-if="filteredResults.length">
                <div v-for="(s, i) in filteredResults" :key="s.code" class="search-box__item"
                  :class="{ 'search-box__item--active': i === activeIndex }"
                  @click="selectStock(s)" @mouseenter="activeIndex = i">
                  <span class="search-box__code">{{ s.code }}</span>
                  <span class="search-box__name">{{ s.name }}</span>
                  <span :class="['badge', s.exchange === 'SH' ? 'badge--sh' : 'badge--sz']">{{ s.exchange === 'SH' ? '沪' : '深' }}</span>
                </div>
              </template>
              <div class="search-box__empty" v-else-if="searchKeyword">未找到匹配股票</div>
            </div>
          </div>

          <div class="filter-date-group" style="display:flex;align-items:center;gap:8px">
            <div class="date-picker" :class="{ 'date-picker--empty': !vm.dateFrom.value }" @click="openDatePicker('from')" style="height:32px;padding:0 10px;display:flex;align-items:center;background:var(--bg-root);border:1px solid var(--border-default);border-radius:var(--radius-md);cursor:pointer;gap:6px">
              <span class="date-picker__label">{{ vm.dateFrom.value || '起始日期' }}</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
              <input ref="dateFromRef" v-model="vm.dateFrom.value" type="date" style="position:absolute;inset:0;opacity:0;cursor:pointer" />
            </div>
            <span class="filter-sep" style="color:var(--text-tertiary)">—</span>
            <div class="date-picker" :class="{ 'date-picker--empty': !vm.dateTo.value }" @click="openDatePicker('to')" style="height:32px;padding:0 10px;display:flex;align-items:center;background:var(--bg-root);border:1px solid var(--border-default);border-radius:var(--radius-md);cursor:pointer;gap:6px">
              <span class="date-picker__label">{{ vm.dateTo.value || '截止日期' }}</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
              <input ref="dateToRef" v-model="vm.dateTo.value" type="date" style="position:absolute;inset:0;opacity:0;cursor:pointer" />
            </div>
          </div>

          <button class="btn-primary" style="padding:4px 14px;font-size:12px" @click="vm.onSearch()">查询</button>
        </div>

        <template v-if="vm.notifications.value.length">
          <div class="stock-panel__body">
            <div class="stock-table-wrap">
              <table class="stock-table">
            <thead>
              <tr>
                <th class="col-type">类型</th>
                <th class="col-stock">股票</th>
                <th class="col-msg">内容</th>
                <th class="col-time">时间</th>
                <th class="col-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(n, i) in vm.notifications.value"
                :key="n.id"
                :class="{
                  'notify-row--unread': !n.isRead,
                  'stock-table__row--stripe': i % 2 === 1,
                }"
              >
                <td class="col-type">
                  <span class="type-badge" :class="`type-badge--${n.type}`">
                    {{ TYPE_LABEL[n.type] || n.type }}
                  </span>
                </td>
                <td class="col-stock">
                  <span class="stock-link" @click="goToKline(n.stockCode, n.stockName)" style="cursor:pointer">
                    <span class="stock-link__code">{{ n.stockCode }}</span>
                    <span class="stock-link__name">{{ n.stockName }}</span>
                  </span>
                </td>
                <td class="col-msg">{{ n.message }}</td>
                <td class="time-cell">{{ formatTime(n.createdAt) }}</td>
                <td>
                  <button
                    v-if="!n.isRead"
                    class="btn-ghost mark-read-btn"
                    @click="vm.markAsRead(n.id)"
                  >标为已读</button>
                  <span v-else class="read-label">已读</span>
                </td>
              </tr>
            </tbody>
            </table>
            </div>
            <div class="stock-panel__pagination" v-if="vm.total.value > vm.pageSize.value">
              <el-pagination size="small" background v-model:current-page="vm.page"
                v-model:page-size="vm.pageSize" :page-sizes="[10,20,30,50]"
                :total="vm.total.value"
                layout="sizes, prev, pager, next"
                @size-change="vm.onSizeChange" @current-change="vm.onPageChange" />
            </div>
          </div>
        </template>

        <div class="stock-panel__empty" v-else>
          <p style="font-size:44px;opacity:0.3;margin-bottom:10px">◈</p>
          <p>{{ vm.activeTab.value === 'all' ? '暂无通知' : '该分类暂无通知' }}</p>
        </div>
      </section>
    </div>
  </div>

  <!-- 登录对话框 -->
  <LoginDialog
    :visible="loginDialogVisible"
    @update:visible="loginDialogVisible = $event"
    @login-success="onLoginSuccess"
  />
</template>

<style scoped>
.notifications-layout {
  display: flex;
  gap: 20px;
  height: calc(100vh - 120px);
}

/* ════════════════════════════════════════════
   Sidebar
   ════════════════════════════════════════════ */
.notify-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
}
.notify-sidebar__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.notify-sidebar__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 1px;
}
.notify-sidebar__read-all-btn {
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 500;
}
.notify-sidebar__list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.notify-sidebar__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  position: relative;
  user-select: none;
}
.notify-sidebar__item:hover {
  background: var(--bg-hover);
}
.notify-sidebar__item--active {
  background: var(--accent-subtle);
}
.notify-sidebar__bar {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 0;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
  transition: height var(--duration-normal) var(--ease-out);
}
.notify-sidebar__item--active .notify-sidebar__bar {
  height: 60%;
}
.notify-sidebar__icon {
  font-size: 14px;
  opacity: 0.5;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
}
.notify-sidebar__item--active .notify-sidebar__icon {
  opacity: 1;
  color: var(--accent);
}
.notify-sidebar__label {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notify-sidebar__badge {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 18px;
  padding: 0 5px;
  border-radius: 10px;
  background: var(--price-up);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  font-family: var(--font-mono);
  line-height: 1;
  flex-shrink: 0;
}

/* ── 股票搜索（对齐 KlineView） ── */
.search-box {
  position: relative;
  width: 240px;
  flex-shrink: 0;
}
.search-box__icon {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  pointer-events: none;
}
.search-box:focus-within .search-box__icon {
  color: var(--accent);
}
.search-box__input {
  width: 100%;
  padding: 8px 12px 8px 33px;
  background: var(--bg-root);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 13px;
  font-family: var(--font-sans);
  outline: none;
  height: 34px;
}
.search-box__input:focus {
  border-color: var(--accent);
  box-shadow: var(--shadow-glow);
}
.search-box__input::placeholder {
  color: var(--text-tertiary);
}
.search-box__dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  background: var(--bg-overlay);
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  max-height: 260px;
  overflow-y: auto;
  z-index: 50;
  backdrop-filter: blur(12px);
}
.search-box__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--border-subtle);
}
.search-box__item:last-child {
  border-bottom: none;
}
.search-box__item:hover,
.search-box__item--active {
  background: var(--bg-hover);
}
.search-box__item--active {
  border-left: 2px solid var(--accent);
  padding-left: 12px;
}
.search-box__code {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--accent);
  min-width: 68px;
}
.search-box__name {
  font-size: 13px;
  color: var(--text-primary);
  flex: 1;
}
.search-box__empty {
  padding: 28px 14px;
  text-align: center;
  font-size: 13px;
  color: var(--text-tertiary);
}

/* ── 日期组 ── */
.filter-date-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.date-picker {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 155px;
  height: 34px;
  padding: 0 10px;
  background: var(--bg-root);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
  user-select: none;
}
.date-picker:hover {
  border-color: var(--border-emphasis);
}
.date-picker:focus-within {
  border-color: var(--accent);
  box-shadow: var(--shadow-glow);
}
.date-picker__label {
  font-size: 13px;
  font-family: var(--font-mono);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.date-picker--empty .date-picker__label {
  color: var(--text-tertiary);
}
.date-picker__icon {
  display: flex;
  align-items: center;
  color: var(--text-tertiary);
  flex-shrink: 0;
  margin-left: 6px;
  pointer-events: none;
}
.date-picker:hover .date-picker__icon {
  color: var(--text-secondary);
}
/* 原生 input 透明覆盖整个区域，点击任意位置触发日历 */
.date-picker__input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
  color-scheme: dark;
}
.date-picker__input::-webkit-calendar-picker-indicator {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  cursor: pointer;
}
.filter-sep {
  color: var(--text-tertiary);
  font-size: 13px;
  flex-shrink: 0;
}

/* ── 复用 stock-panel 基础样式（scoped 隔离，不继承自 GroupsView） ── */
.stock-panel {
  flex: 1;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 16px 22px 14px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* ── 复用 stock-table 基础样式（scoped 隔离） ── */
.stock-table {
  width: 100%;
  border-collapse: collapse;
  background: transparent;
}
.stock-table th {
  text-align: left;
  padding: 7px 12px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border-default);
  position: sticky;
  top: 0;
  background: transparent;
}
.stock-table td {
  padding: 9px 12px;
  font-size: 13px;
  border-bottom: 1px solid var(--border-subtle);
  background: transparent;
}
.stock-table tbody tr {
  transition: background var(--duration-fast);
}
.stock-table tbody tr:hover {
  background: var(--bg-hover);
}
.stock-table__row--stripe {
  background: rgba(255, 255, 255, 0.008);
}
.stock-panel__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.stock-table-wrap {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  background: transparent;
}
.stock-panel__pagination {
  display: flex;
  justify-content: flex-end;
  padding: 8px 0 2px;
  margin-top: auto;
  background: var(--bg-surface);
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

/* ── Column alignment ── */
.stock-table th.col-type, .stock-table td.col-type { text-align: center; }
.stock-table th.col-stock, .stock-table td.col-stock { text-align: center; }
.stock-table th.col-msg, .stock-table td.col-msg { text-align: center; }
.stock-table th.col-time, .stock-table td.time-cell { text-align: center; }
.stock-table th.col-action, .stock-table td:last-child { text-align: center; }

.stock-panel__pagination :deep(.el-pagination__sizes) { margin-right: 0; }
.stock-panel__pagination :deep(.el-select) { width: 90px; }
.stock-panel__pagination :deep(.el-select .el-input__wrapper) {
  background: transparent;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.06) inset;
  font-size: 12px;
  height: 26px;
}
.stock-panel__pagination :deep(.el-select .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(255,255,255,0.12) inset;
}
.stock-panel__pagination :deep(.el-select .el-input__wrapper.is-focused) {
  box-shadow: 0 0 0 1px rgba(255,255,255,0.15) inset;
}
.stock-panel__pagination :deep(.el-select .el-input__inner) {
  color: var(--text-primary);
}

/* ── Empty state ── */
.stock-panel__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 14px;
  gap: 10px;
}

/* ── Unread row highlight ── */
.notify-row--unread {
  background: transparent;
}
.notify-row--unread:hover {
  background: var(--bg-hover) !important;
}

/* ── Type Badge ── */
.type-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.type-badge--GOLDEN_CROSS     { background: rgba(217, 161, 54, 0.15);  color: #d9a136; }
.type-badge--WHITE_LINE_BUY   { background: rgba(59, 140, 227, 0.15);  color: var(--accent); }
.type-badge--YELLOW_LINE_BUY  { background: rgba(201, 168, 54, 0.15);  color: #c9a836; }
.type-badge--CLEAR_POSITION   { background: rgba(239, 83, 80, 0.15);   color: var(--price-up); }
.type-badge--RE_ATTENTION     { background: rgba(38, 166, 154, 0.15);  color: var(--price-down); }

/* ── Stock Link ── */
.stock-link {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
}
.stock-link__code {
  font-family: var(--font-mono);
  color: var(--accent);
  font-size: 13px;
  font-weight: 500;
}
.stock-link__name {
  color: var(--text-primary);
  font-weight: 500;
}
.stock-link:hover .stock-link__name {
  color: var(--accent);
}

/* ── Message / Time ── */
.msg-cell {
  color: var(--text-secondary);
  line-height: 1.5;
}
.time-cell {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-tertiary);
}

.mark-read-btn {
  padding: 3px 12px;
  font-size: 11px;
}
.read-label {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
