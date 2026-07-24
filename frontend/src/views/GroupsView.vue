<script setup lang="ts">
import { computed, shallowRef, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useGroupManager, useStockSearch } from '../composables/useGroupManager'

const router = useRouter()
const gm = useGroupManager()
const stockSearch = useStockSearch()

// 分页
const stockPage = shallowRef(1)
const stockPageSize = 10

const pagedStocks = computed(() => {
  const list = gm.groupStocks.value
  const start = (stockPage.value - 1) * stockPageSize
  return list.slice(start, start + stockPageSize)
})

const stockTotal = computed(() => gm.groupStocks.value.length)

// 对话框状态
const showDialog = shallowRef(false)
const editingGroup = shallowRef<any>(null)
const saving = shallowRef(false)
const groupForm = shallowRef({ name: '', description: '' })

const showAddStock = shallowRef(false)
const pendingStock = shallowRef<any>(null)

function showCreateDialog() {
  editingGroup.value = null
  groupForm.value = { name: '', description: '' }
  showDialog.value = true
}

function editGroup(g: any) {
  editingGroup.value = g
  groupForm.value = { name: g.name, description: g.description || '' }
  showDialog.value = true
}

async function saveGroup() {
  if (!groupForm.value.name.trim()) return
  saving.value = true
  try {
    await gm.saveGroup(groupForm.value.name, groupForm.value.description, editingGroup.value?.id)
    showDialog.value = false
  } finally { saving.value = false }
}

async function deleteGroup(g: any) {
  if (!confirm(`确认删除分组「${g.name}」？`)) return
  await gm.deleteGroup(g.id)
}

function selectAddStock(s: any) {
  pendingStock.value = s
  stockSearch.keyword.value = `${s.code} ${s.name}`
  stockSearch.results.value = []
}

async function confirmAddStock() {
  if (!pendingStock.value) return
  await gm.addStock(pendingStock.value.code)
  showAddStock.value = false
  pendingStock.value = null
  stockSearch.keyword.value = ''
}

async function switchGroup(g: any) {
  stockPage.value = 1
  await gm.selectGroup(g)
}

function viewKline(code: string) {
  router.push({ name: 'Kline', query: { code } })
}

async function initPage() {
  await gm.loadGroups()
  // 默认选中自选股，不存在则创建
  let watchlist = gm.groups.value.find((g: any) => g.name === '自选股')
  if (!watchlist) {
    await gm.saveGroup('自选股', '')
    await gm.loadGroups()
    watchlist = gm.groups.value.find((g: any) => g.name === '自选股')
  }
  if (watchlist) {
    await gm.selectGroup(watchlist)
  }
}

onMounted(() => initPage())
</script>

<template>
  <div class="groups-page">
    <div class="groups-layout">
      <!-- 左侧分组栏 -->
      <aside class="group-sidebar">
        <div class="group-sidebar__head">
          <h3 class="group-sidebar__title">我的分组</h3>
          <button class="btn-primary group-sidebar__add-btn" @click="showCreateDialog">+ 新建</button>
        </div>
        <div class="group-sidebar__list" v-if="gm.groups.value.length">
          <div
            v-for="g in gm.groups.value"
            :key="g.id"
            class="group-sidebar__item"
            :class="{ 'group-sidebar__item--active': gm.activeGroup.value?.id === g.id }"
            @click="switchGroup(g)"
          >
            <span class="group-sidebar__bar"></span>
            <span class="group-sidebar__name">{{ g.name }}</span>
            <span class="group-sidebar__count">{{ g._stockCount || 0 }}</span>
            <div class="group-sidebar__actions" v-if="g.name !== '自选股'">
              <button class="group-sidebar__action-btn" @click.stop="editGroup(g)">编辑</button>
              <button class="group-sidebar__action-btn group-sidebar__action-btn--danger" @click.stop="deleteGroup(g)">删除</button>
            </div>
          </div>
        </div>
        <div class="group-sidebar__empty" v-else>
          <p class="group-sidebar__empty-icon">⊞</p>
          <p>暂无分组</p>
          <p class="group-sidebar__hint">点击「新建」创建第一个分组</p>
        </div>
      </aside>

      <!-- 右侧股票面板 -->
      <section class="stock-panel">
        <template v-if="gm.activeGroup.value">
          <div class="stock-panel__head">
            <div>
              <h3 class="stock-panel__name">{{ gm.activeGroup.value.name }}</h3>
              <p class="stock-panel__desc" v-if="gm.activeGroup.value.description">{{ gm.activeGroup.value.description }}</p>
            </div>
            <button class="btn-primary stock-panel__add-btn" @click="showAddStock = true">+ 添加股票</button>
          </div>

          <template v-if="gm.groupStocks.value.length">
            <div class="stock-panel__body">
              <table class="stock-table">
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>名称</th>
                    <th>所属行业</th>
                    <th>查看K线</th>
                    <th>移出分组</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(s, i) in pagedStocks" :key="s.code" :class="{ 'stock-table__row--stripe': i % 2 === 1 }">
                    <td><span class="stock-table__code">{{ s.code }}</span></td>
                    <td class="stock-table__name">{{ s.name }}</td>
                    <td class="stock-table__industry">{{ s.industry || '-' }}</td>
                    <td>
                      <button class="btn-ghost stock-table__kline-btn" @click="viewKline(s.code)">K线</button>
                    </td>
                    <td>
                      <button class="btn-ghost btn-ghost--danger stock-table__remove-btn" @click="gm.removeStock(s.code)">移除</button>
                    </td>
                  </tr>
                </tbody>
              </table>

              <div class="stock-panel__pagination" v-if="stockTotal > stockPageSize">
                <el-pagination
                  size="small"
                  background
                  :current-page="stockPage"
                  :page-size="stockPageSize"
                  :total="stockTotal"
                  layout="prev, pager, next"
                  @current-change="(p: number) => stockPage = p"
                />
              </div>
            </div>
          </template>

          <div class="stock-panel__empty" v-else>
            <p class="stock-panel__empty-icon">◫</p>
            <p>暂未添加股票</p>
            <p class="stock-panel__hint">点击「添加股票」搜索并加入</p>
          </div>
        </template>

        <div class="stock-panel__placeholder" v-else>
          <div class="stock-panel__placeholder-icon">⊞</div>
          <p>选择一个分组查看股票</p>
        </div>
      </section>
    </div>

    <!-- 分组编辑对话框 -->
    <div class="modal-overlay" v-if="showDialog" @click.self="showDialog = false">
      <div class="modal-card">
        <h3 class="modal-card__title">{{ editingGroup ? '编辑分组' : '新建分组' }}</h3>
        <form @submit.prevent="saveGroup" class="modal-form">
          <div class="modal-form__group">
            <label class="modal-form__label">名称</label>
            <input v-model="groupForm.name" type="text" class="input-dark"
                   placeholder="分组名称" maxlength="50" autofocus />
          </div>
          <div class="modal-form__group">
            <label class="modal-form__label">描述</label>
            <input v-model="groupForm.description" type="text" class="input-dark"
                   placeholder="可选描述" maxlength="200" />
          </div>
          <div class="modal-form__actions">
            <button type="button" class="btn-ghost" @click="showDialog = false">取消</button>
            <button type="submit" class="btn-primary" :disabled="saving">
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 添加股票对话框 -->
    <div class="modal-overlay" v-if="showAddStock" @click.self="showAddStock = false">
      <div class="modal-card modal-card--sm">
        <h3 class="modal-card__title">添加股票</h3>
        <div class="modal-form__group">
          <label class="modal-form__label">搜索股票</label>
          <input
            :value="stockSearch.keyword.value"
            @input="stockSearch.search(($event.target as HTMLInputElement).value)"
            type="text"
            class="input-dark"
            placeholder="输入代码或名称搜索"
          />
          <div class="modal-form__search-results" v-if="stockSearch.results.value.length">
            <div
              v-for="s in stockSearch.results.value"
              :key="s.code"
              class="modal-form__search-item"
              @click="selectAddStock(s)"
            >
              <span class="modal-form__search-code">{{ s.code }}</span>
              <span>{{ s.name }}</span>
              <span :class="['badge', s.exchange === 'SH' ? 'badge--sh' : 'badge--sz']" style="margin-left: auto;">
                {{ s.exchange === 'SH' ? '沪' : '深' }}
              </span>
            </div>
          </div>
        </div>
        <div class="modal-form__actions">
          <button type="button" class="btn-ghost" @click="showAddStock = false">取消</button>
          <button class="btn-primary" :disabled="!pendingStock" @click="confirmAddStock">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.groups-layout {
  display: flex;
  gap: 20px;
  height: calc(100vh - 120px);
}

/* ── Sidebar ── */
.group-sidebar {
  width: 260px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
}
.group-sidebar__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.group-sidebar__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 1px;
}
.group-sidebar__add-btn {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
}
.group-sidebar__list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.group-sidebar__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  position: relative;
}
.group-sidebar__item:hover {
  background: var(--bg-hover);
}
.group-sidebar__item--active {
  background: var(--accent-subtle);
}
.group-sidebar__bar {
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
.group-sidebar__item--active .group-sidebar__bar {
  height: 60%;
}
.group-sidebar__name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-sidebar__count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 1px 7px;
  background: var(--bg-root);
  border-radius: var(--radius-pill);
  min-width: 22px;
  text-align: center;
}
.group-sidebar__actions {
  display: none;
  gap: 4px;
}
.group-sidebar__item:hover .group-sidebar__actions {
  display: flex;
}
.group-sidebar__action-btn {
  padding: 2px 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  font-size: 11px;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.group-sidebar__action-btn:hover {
  background: var(--bg-raised);
  color: var(--text-primary);
}
.group-sidebar__action-btn--danger:hover {
  color: var(--price-up);
  background: var(--price-up-bg);
}
.group-sidebar__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 13px;
  gap: 6px;
}
.group-sidebar__empty-icon {
  font-size: 28px;
  opacity: 0.4;
  margin-bottom: 4px;
}
.group-sidebar__hint {
  font-size: 12px;
  color: var(--text-tertiary);
  opacity: 0.7;
}

/* ── Stock Panel ── */
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
.stock-panel__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  flex-shrink: 0;
}
.stock-panel__name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}
.stock-panel__desc {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}
.stock-panel__add-btn {
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 500;
  flex-shrink: 0;
}

/* Table */
.stock-panel__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
}
.stock-panel__body .stock-table {
  margin-bottom: 0;
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
.stock-table {
  width: 100%;
  border-collapse: collapse;
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
  background: var(--bg-surface);
}
.stock-table td {
  padding: 7px 12px;
  font-size: 13px;
  border-bottom: 1px solid var(--border-subtle);
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
.stock-table__code {
  font-family: var(--font-mono);
  color: var(--accent);
  font-size: 13px;
  font-weight: 500;
}
.stock-table__name {
  font-weight: 500;
}
.stock-table__industry {
  font-size: 12px;
  color: var(--text-secondary);
}
.stock-table__kline-btn {
  padding: 3px 12px;
  font-size: 12px;
  color: var(--accent);
}
.stock-table__kline-btn:hover {
  background: var(--accent-subtle);
}
.stock-table__remove-btn {
  padding: 3px 10px;
  font-size: 11px;
}

.stock-panel__empty,
.stock-panel__placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 14px;
  gap: 8px;
}
.stock-panel__empty-icon,
.stock-panel__placeholder-icon {
  font-size: 40px;
  opacity: 0.35;
}
.stock-panel__hint {
  font-size: 12px;
  opacity: 0.6;
}

/* ── Modal ── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  backdrop-filter: blur(4px);
  animation: fade-in var(--duration-fast) var(--ease-out);
}
.modal-card {
  width: 420px;
  padding: 28px;
  background: var(--bg-surface);
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  animation: slide-up var(--duration-slow) var(--ease-out);
}
.modal-card--sm {
  width: 440px;
}
.modal-card__title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 22px;
  color: var(--text-primary);
}
.modal-form {
  display: flex;
  flex-direction: column;
}
.modal-form__group {
  margin-bottom: 18px;
  position: relative;
}
.modal-form__label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.modal-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 22px;
}
.modal-form__search-results {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  max-height: 200px;
  overflow-y: auto;
  background: var(--bg-overlay);
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  z-index: 10;
  margin-top: 4px;
  animation: dropdown-in var(--duration-fast) var(--ease-out);
}
.modal-form__search-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--duration-fast);
}
.modal-form__search-item:last-child {
  border-bottom: none;
}
.modal-form__search-item:hover {
  background: var(--bg-hover);
}
.modal-form__search-code {
  font-family: var(--font-mono);
  color: var(--accent);
  font-size: 13px;
  min-width: 70px;
  font-weight: 500;
}
</style>
