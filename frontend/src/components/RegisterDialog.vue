<template>
  <el-dialog
    :model-value="isOpen"
    @update:model-value="isOpen = $event"
    title="注册新账号"
    width="400px"
    :close-on-click-modal="true"
    :close-on-press-escape="true"
    class="register-dialog"
    @close="closeDialog"
  >
    <div class="register-form">
      <div class="form-group">
        <label class="form-label">用户名</label>
        <el-input
          v-model="username"
          type="text"
          placeholder="请输入用户名"
          autocomplete="username"
        />
      </div>

      <div class="form-group">
        <label class="form-label">密码</label>
        <el-input
          v-model="password"
          type="password"
          placeholder="至少 6 位字符"
          autocomplete="new-password"
        />
      </div>

      <div class="form-group">
        <label class="form-label">验证码</label>
        <div class="captcha-group">
          <el-input
            v-model="captchaCode"
            type="text"
            placeholder="请输入验证码"
            maxlength="4"
            autocomplete="off"
          />
          <img
            :src="captchaImage"
            @click="refreshCaptcha"
            class="captcha-image"
            alt="验证码"
            title="点击刷新验证码"
          />
        </div>
      </div>

      <p class="form-error" v-if="errorMsg">{{ errorMsg }}</p>

      <div class="form-actions">
        <el-button
          type="primary"
          :loading="loading"
          @click="handleRegister"
          class="register-btn"
        >
          注 册
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { authApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits(['update:visible', 'register-success'])

const isOpen = ref(false)
const router = useRouter()
const store = useAuthStore()
const loading = ref(false)
const errorMsg = ref('')
const username = ref('')
const password = ref('')
const captchaId = ref('')
const captchaCode = ref('')
const captchaImage = ref('')

// 关闭对话框
const closeDialog = () => {
  emit('update:visible', false)
  isOpen.value = false
  // 清空表单
  username.value = ''
  password.value = ''
  captchaCode.value = ''
  errorMsg.value = ''
}

// 监听可见性变化（immediate 处理 v-if 首次创建时 props.visible 已为 true 的情况）
watch(() => props.visible, (newVal) => {
  isOpen.value = newVal
  if (newVal) {
    refreshCaptcha()
  }
}, { immediate: true })

// 刷新验证码
async function refreshCaptcha() {
  try {
    const res = await authApi.captcha()
    if (res.data && res.data.captchaId && res.data.captchaImage) {
      captchaId.value = res.data.captchaId
      captchaImage.value = res.data.captchaImage
    } else {
      throw new Error('Invalid captcha response')
    }
  } catch (error) {
    console.error('获取验证码失败:', error)
    // 使用备用验证码图片
    captchaImage.value = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNDAiIHZpZXdCb3g9IjAgMCA0MCA0MCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjQwIiBoZWlnaHQ9IjQwIiByeD0iMjAiIGZpbGw9IiNGRjY2NjYiLz4KPHBhdGggZD0iTTIwLjQ1IDIwLjE1QzIwLjQ1IDE1LjQ2IDIwIDE2LjM2IDIwIDE3QzIwIDE4LjY2IDIwLjQ1IDIwIDIwIDIwUzIwLjc1IDIwIDIwLjE1IDIwLjE1SDIwLjQ1VjIwWiIgc3Ryb2tlPSIjMDAwIiBzdHJva2Utd2lkdGg9IjEiLz4KPC9zdmc+'
  }
}

// 处理注册
async function handleRegister() {
  errorMsg.value = ''
  if (!username.value.trim()) {
    errorMsg.value = '请输入用户名'
    return
  }
  if (password.value.length < 6) {
    errorMsg.value = '密码至少 6 位'
    return
  }
  if (!captchaCode.value.trim()) {
    errorMsg.value = '请输入验证码'
    return
  }

  loading.value = true
  try {
    const res = await authApi.register({
      username: username.value,
      password: password.value,
      captchaId: captchaId.value,
      captchaCode: captchaCode.value,
    })
    store.setAuth(res.data.token, username.value)
    emit('register-success')
    closeDialog()
    router.push('/')
  } catch (error: any) {
    errorMsg.value = error?.msg || '注册失败'
    refreshCaptcha()
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-dialog :deep(.el-dialog__header) {
  padding: 20px 24px 0;
  border-bottom: 1px solid var(--border-default);
}

.register-dialog :deep(.el-dialog__body) {
  padding: 24px;
}

.register-dialog :deep(.el-dialog__footer) {
  padding: 0 24px 20px;
}

.form-group {
  margin-bottom: 20px;
}

.form-label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
}

.form-error {
  color: #ef4444;
  font-size: 13px;
  margin-bottom: 16px;
  text-align: center;
}

.form-actions {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}

.register-btn {
  min-width: 120px;
}

.captcha-group {
  display: flex;
  gap: 10px;
  align-items: center;
}

.captcha-image {
  height: 36px;
  cursor: pointer;
  border-radius: 4px;
  border: 1px solid var(--border-default);
  object-fit: contain;
}

.captcha-image:hover {
  border-color: var(--accent);
}
</style>