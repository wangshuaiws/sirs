import { shallowRef } from 'vue'
import { stockApi } from '../api'

export function useStockSearch() {
  const keyword = shallowRef('')
  const results = shallowRef<any[]>([])
  const searching = shallowRef(false)

  let timeout: ReturnType<typeof setTimeout>

  function search(kw: string) {
    clearTimeout(timeout)
    keyword.value = kw
    if (!kw.trim()) {
      results.value = []
      return
    }
    timeout = setTimeout(async () => {
      searching.value = true
      try {
        const res = await stockApi.search(kw.trim())
        results.value = res.data || []
      } finally {
        searching.value = false
      }
    }, 300)
  }

  return { keyword, results, searching, search }
}
