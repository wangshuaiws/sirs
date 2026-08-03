<template>
  <div id="app-root">
    <!-- 顶部导航栏 -->
    <header class="nav-header">
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
          <span class="nav-link" :class="{ 'nav-link--active': route.path === '/groups' }" @click="goToGroups">
            <span class="nav-link__icon">⊞</span>
            <span>分组管理</span>
          </span>
          <span class="nav-link" :class="{ 'nav-link--active': route.path === '/notifications' }" @click="goToNotifications">
            <span class="nav-link__icon">⚡</span>
            <span>通知中心</span>
          </span>
        </nav>
        <div class="nav-user">
          <div class="user-avatar" v-if="store.isLoggedIn()">{{ store.username.charAt(0).toUpperCase() }}</div>
          <span class="user-name" v-if="store.isLoggedIn()">{{ store.username }}</span>
          <button class="btn-logout" v-if="store.isLoggedIn()" @click="logout">
            <span class="btn-logout__icon">⏻</span>
            退出
          </button>
          <template v-else>
            <button class="btn-login" @click="showLoginDialog = true">登录</button>
            <button class="btn-register" @click="showRegisterDialog = true">注册</button>
          </template>
        </div>
      </div>
    </header>

    <!-- 登录对话框 -->
    <LoginDialog
      v-if="showLoginDialog"
      :visible="showLoginDialog"
      @update:visible="showLoginDialog = $event"
      @login-success="onLoginSuccess"
    />

    <!-- 注册对话框 -->
    <RegisterDialog
      v-if="showRegisterDialog"
      :visible="showRegisterDialog"
      @update:visible="showRegisterDialog = $event"
      @register-success="onRegisterSuccess"
    />

    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import LoginDialog from './components/LoginDialog.vue'
import RegisterDialog from './components/RegisterDialog.vue'

const route = useRoute()
const router = useRouter()
const store = useAuthStore()
const showLoginDialog = ref(false)
const showRegisterDialog = ref(false)

// 登录过期（后端 code=1003，主动操作场景）：弹全局登录框
function onAuthExpired() {
  showLoginDialog.value = true
}
onMounted(() => window.addEventListener('auth-expired', onAuthExpired))
onUnmounted(() => window.removeEventListener('auth-expired', onAuthExpired))

function logout() {
  store.clearAuth()
  router.push('/')
}

// 登录成功回调
const onLoginSuccess = () => {
  showLoginDialog.value = false
  // 如果当前在分组/通知页，登录后刷新数据
  if (route.path === '/groups') {
    // 触发 GroupsView 重新加载 — 通过路由刷新
    router.replace('/groups')
  } else if (route.path === '/notifications') {
    router.replace('/notifications')
  }
}

// 注册成功回调
const onRegisterSuccess = () => {
  showRegisterDialog.value = false
  if (route.path === '/groups') {
    router.replace('/groups')
  } else if (route.path === '/notifications') {
    router.replace('/notifications')
  }
}

// 导航守卫：未登录则弹登录框
function goToGroups() {
  if (store.isLoggedIn()) {
    router.push('/groups')
  } else {
    showLoginDialog.value = true
  }
}

function goToNotifications() {
  if (store.isLoggedIn()) {
    router.push('/notifications')
  } else {
    showLoginDialog.value = true
  }
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
  cursor: pointer;
  user-select: none;
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

/* ── Auth Buttons ── */
.btn-login, .btn-register {
  padding: 5px 12px;
  border-radius: var(--radius-md);
  font-size: 12px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  border: 1px solid var(--border-default);
}

.btn-login {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.btn-login:hover {
  opacity: 0.9;
  background: var(--accent);
  border-color: var(--accent);
}

.btn-register {
  background: transparent;
  color: var(--text-secondary);
}

.btn-register:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
  border-color: var(--border-default);
}

/* ── Main Content ── */
.main-content {
  flex: 1;
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}
</style>
