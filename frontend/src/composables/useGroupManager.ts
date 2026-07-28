import { shallowRef } from 'vue'
import { groupApi, stockApi } from '../api'

export function useGroupManager() {
  const groups = shallowRef<any[]>([])
  const activeGroup = shallowRef<any>(null)
  const groupStocks = shallowRef<any[]>([])
  const groupStockTotal = shallowRef(0)
  let _currentPage = 1
  let _pageSize = 10

  async function loadGroups() {
    const res = await groupApi.list()
    groups.value = (res.data || []).map((g: any) => ({ ...g, _stockCount: 0 }))
  }

  async function selectGroup(g: any, page = 1, size = 10) {
    activeGroup.value = g
    _currentPage = page
    _pageSize = size
    const res = await groupApi.getStocks(g.id, page, size)
    groupStocks.value = res.data?.records || []
    groupStockTotal.value = res.data?.total || 0
  }

  async function saveGroup(name: string, description: string, editingId?: number) {
    if (editingId) {
      await groupApi.update(editingId, { name, description })
    } else {
      await groupApi.create({ name, description })
    }
    await loadGroups()
  }

  async function deleteGroup(id: number) {
    await groupApi.delete(id)
    if (activeGroup.value?.id === id) {
      activeGroup.value = null
      groupStocks.value = []
    }
    await loadGroups()
  }

  async function removeStock(code: string) {
    if (!activeGroup.value) return
    await groupApi.removeStock(activeGroup.value.id, code)
    await selectGroup(activeGroup.value, _currentPage, _pageSize)
  }

  async function addStock(code: string) {
    if (!activeGroup.value) return
    await groupApi.addStock(activeGroup.value.id, code)
    await selectGroup(activeGroup.value, _currentPage, _pageSize)
  }

  return {
    groups, activeGroup, groupStocks, groupStockTotal,
    loadGroups, selectGroup,
    saveGroup, deleteGroup,
    removeStock, addStock,
  }
}

export function useStockSearch() {
  const keyword = shallowRef('')
  const results = shallowRef<any[]>([])

  let timer: ReturnType<typeof setTimeout>
  function search(kw: string) {
    clearTimeout(timer)
    keyword.value = kw
    if (!kw.trim()) { results.value = []; return }
    timer = setTimeout(async () => {
      try {
        const res = await stockApi.search(kw.trim())
        results.value = res.data || []
      } catch { /* */ }
    }, 300)
  }

  return { keyword, results, search }
}
