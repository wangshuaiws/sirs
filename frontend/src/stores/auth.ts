import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')

  function setAuth(t: string, name: string) {
    token.value = t
    username.value = name
    localStorage.setItem('token', t)
    localStorage.setItem('username', name)
  }

  function clearAuth() {
    token.value = ''
    username.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('username')
  }

  function isLoggedIn() {
    return !!token.value
  }

  return { token, username, setAuth, clearAuth, isLoggedIn }
})
