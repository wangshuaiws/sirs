<script setup lang="ts">
import { shallowRef, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../api'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const store = useAuthStore()
const loading = shallowRef(false)
const errorMsg = shallowRef('')
const captchaImg = shallowRef('')
const captchaId = shallowRef('')
const username = shallowRef('')
const password = shallowRef('')
const captchaCode = shallowRef('')

async function refreshCaptcha() {
  const res = await authApi.captcha()
  captchaId.value = res.data.captchaId
  captchaImg.value = res.data.captchaImage
}

async function handleRegister() {
  errorMsg.value = ''
  if (!username.value.trim()) { errorMsg.value = '请输入用户名'; return }
  if (password.value.length < 6) { errorMsg.value = '密码至少 6 位'; return }
  if (!captchaCode.value.trim()) { errorMsg.value = '请输入验证码'; return }

  loading.value = true
  try {
    const res = await authApi.register({
      username: username.value,
      password: password.value,
      captchaId: captchaId.value,
      captchaCode: captchaCode.value,
    })
    store.setAuth(res.data.token, username.value)
    router.push('/')
  } catch (e: any) {
    errorMsg.value = e?.msg || '注册失败'
    refreshCaptcha()
  } finally {
    loading.value = false
  }
}

onMounted(refreshCaptcha)
</script>

<template>
  <div class="auth-page">
    <div class="auth-bg"></div>
    <div class="auth-card">
      <div class="card-header">
        <div class="card-header__mark">◈</div>
        <h1 class="card-header__title">SIRS</h1>
        <p class="card-header__subtitle">创建新账号</p>
      </div>
      <form @submit.prevent="handleRegister" class="auth-form">
        <div class="auth-form__group">
          <label class="auth-form__label">用户名</label>
          <input
            v-model="username" type="text" class="input-dark"
            placeholder="请输入用户名" autocomplete="username"
          />
        </div>
        <div class="auth-form__group">
          <label class="auth-form__label">密码</label>
          <input
            v-model="password" type="password" class="input-dark"
            placeholder="至少 6 位字符" autocomplete="new-password"
          />
        </div>
        <div class="auth-form__group">
          <label class="auth-form__label">验证码</label>
          <div class="captcha-row">
            <input
              v-model="captchaCode" type="text" class="input-dark captcha-row__input"
              placeholder="输入验证码" autocomplete="off"
            />
            <img :src="captchaImg" class="captcha-row__img" @click="refreshCaptcha" title="点击刷新验证码" />
          </div>
        </div>
        <p class="auth-form__error" v-if="errorMsg">{{ errorMsg }}</p>
        <button type="submit" class="btn-primary auth-form__btn" :disabled="loading">
          {{ loading ? '注册中…' : '注 册' }}
        </button>
      </form>
      <p class="card-footer">
        已有账号？<router-link to="/login">立即登录</router-link>
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
}
.auth-bg {
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse at 15% 40%, rgba(59, 140, 227, 0.07) 0%, transparent 55%),
    radial-gradient(ellipse at 85% 70%, rgba(163, 113, 247, 0.05) 0%, transparent 55%),
    radial-gradient(ellipse at 50% 90%, rgba(217, 161, 54, 0.03) 0%, transparent 50%),
    var(--bg-root);
}
.auth-card {
  position: relative;
  width: 420px;
  padding: 40px 36px 32px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  animation: slide-up var(--duration-slow) var(--ease-out);
}

/* Header */
.card-header {
  text-align: center;
  margin-bottom: 32px;
}
.card-header__mark {
  font-size: 36px;
  color: var(--accent);
  margin-bottom: 8px;
}
.card-header__title {
  font-family: var(--font-mono);
  font-size: 24px;
  font-weight: 600;
  letter-spacing: 4px;
  color: var(--text-primary);
}
.card-header__subtitle {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-tertiary);
}

/* Form */
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.auth-form__group {
  display: flex;
  flex-direction: column;
}
.auth-form__label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.auth-form__error {
  font-size: 13px;
  color: var(--price-up);
  margin: -8px 0 -4px;
}
.auth-form__btn {
  width: 100%;
  padding: 11px;
  margin-top: 4px;
}

/* Captcha */
.captcha-row {
  display: flex;
  gap: 10px;
}
.captcha-row__input {
  flex: 1;
}
.captcha-row__img {
  width: 120px;
  height: 44px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-default);
  cursor: pointer;
  background: #fff;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.captcha-row__img:hover {
  border-color: var(--accent);
}

.card-footer {
  text-align: center;
  margin-top: 24px;
  font-size: 13px;
  color: var(--text-tertiary);
}
</style>
