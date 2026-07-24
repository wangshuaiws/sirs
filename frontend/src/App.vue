<template>
  <div id="app-root">
    <!-- 顶部导航栏 -->
    <header v-if="showNav" class="nav-header">
      <div class="nav-inner">
        <div class="nav-brand">
          <span class="brand-icon">◈</span>
          <span class="brand-text">SIRS</span>
        </div>
        <nav class="nav-links">
          <router-link to="/" class="nav-link" active-class="nav-link--active">
            <span class="nav-link__icon">◫</span>
            <span>K线图</span>
          </router-link>
          <router-link to="/groups" class="nav-link" active-class="nav-link--active">
            <span class="nav-link__icon">⊞</span>
            <span>分组管理</span>
          </router-link>
          <router-link to="/notifications" class="nav-link" active-class="nav-link--active">
            <span class="nav-link__icon">⚡</span>
            <span>通知中心</span>
          </router-link>
        </nav>
        <div class="nav-user">
          <div class="user-avatar">{{ store.username.charAt(0).toUpperCase() }}</div>
          <span class="user-name">{{ store.username }}</span>
          <button class="btn-logout" @click="logout">
            <span class="btn-logout__icon">⏻</span>
            退出
          </button>
        </div>
      </div>
    </header>

    <main class="main-content" :class="{ 'main--full': !showNav }">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { authApi } from './api'

const route = useRoute()
const router = useRouter()
const store = useAuthStore()

const showNav = computed(() => route.path !== '/login' && route.path !== '/register')

// 开发环境：启动时自动用默认用户登录（覆盖旧 token）
onMounted(async () => {
  try {
    const res: any = await authApi.login({ username: 'admin', password: 'admin123' })
    store.setAuth(res.data.token, 'admin')
  } catch { /* 后端未启动时静默失败 */ }
})

function logout() {
  store.clearAuth()
  router.push('/login')
}
</script>

<style scoped>
/* ── Nav Header ── */
.nav-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(9, 12, 16, 0.88);
  backdrop-filter: blur(16px) saturate(120%);
  -webkit-backdrop-filter: blur(16px) saturate(120%);
  border-bottom: 1px solid var(--border-default);
}
.nav-inner {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 24px;
}

/* ── Brand ── */
.nav-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 36px;
}
.brand-icon {
  font-size: 18px;
  color: var(--accent);
}
.brand-text {
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 3px;
  color: var(--text-primary);
  user-select: none;
}

/* ── Nav Links ── */
.nav-links {
  display: flex;
  gap: 2px;
}
.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  transition: all var(--duration-fast) var(--ease-out);
  text-decoration: none;
}
.nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.nav-link--active {
  color: var(--accent) !important;
  background: var(--accent-subtle) !important;
}
.nav-link__icon {
  font-size: 14px;
  opacity: 0.7;
}

/* ── User Area ── */
.nav-user {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent), #a371f7);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
  flex-shrink: 0;
}
.user-name {
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.btn-logout {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-tertiary);
  font-size: 12px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.btn-logout:hover {
  color: var(--price-up);
  border-color: rgba(239, 68, 68, 0.4);
  background: var(--price-up-bg);
}
.btn-logout__icon {
  font-size: 13px;
}

/* ── Main Content ── */
.main-content {
  flex: 1;
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}
.main--full {
  padding: 0;
  max-width: none;
}
</style>
