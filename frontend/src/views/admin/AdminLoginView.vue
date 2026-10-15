<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { ApiError } from '../../utils/request'

const router = useRouter()
const auth = useAuthStore()
const username = ref('admin')
const password = ref('')
const error = ref('')
const busy = ref(false)

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 1002) return '用户名或密码错误（1002），连续失败会触发限流（1008）。'
    if (e.code === 1008) return '登录失败次数过多（1008），请稍后再试。'
    return e.message
  }
  return String(e)
}

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await auth.login(username.value.trim(), password.value, true)
    router.push('/admin')
  } catch (e) {
    error.value = errText(e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <section class="auth-page">
    <div class="eyebrow">ADMIN / SIGN IN</div>
    <h1>进入管理工作台</h1>
    <p class="lede">管理端数据和审核操作需要管理员权限。账号由运维侧在 backend 中预置。</p>
    <form class="form-grid admin-login-form" @submit.prevent="submit">
      <label>用户名<input v-model="username" autocomplete="username" /></label>
      <label>密码<input v-model="password" type="password" autocomplete="current-password" /></label>
    </form>
    <div class="hero-actions">
      <button class="primary" type="button" :disabled="busy" @click="submit">{{ busy ? '登录中…' : '登录管理端' }} ↗</button>
    </div>
    <div v-if="error" class="state-box">{{ error }}</div>
  </section>
</template>
