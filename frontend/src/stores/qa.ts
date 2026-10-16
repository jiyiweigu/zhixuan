import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'

// 一条问答消息：question 先入列（供加载态占位），result / error 异步填充。
// errorData 携带 3001 的 { data_status, missing_rule_sets }，供页面做专项引导。
export interface QaMessage {
  question: string
  at: string
  result?: Zhixuan.QaResult | null
  errorCode?: number
  errorMessage?: string
  errorData?: any
}

export const useQaStore = defineStore('qa', () => {
  const sessionId = ref<string | null>(null)
  const messages = ref<QaMessage[]>([])
  function ensureSession() {
    if (!sessionId.value) sessionId.value = `qa-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
    return sessionId.value
  }
  async function ask(question: string) {
    const text = question.trim()
    if (!text) return null
    const msg: QaMessage = { question: text, at: new Date().toISOString() }
    messages.value.push(msg)
    try {
      msg.result = await api.ask({ question: text, session_id: ensureSession() })
    } catch (e: any) {
      msg.errorCode = e?.code ?? 5000
      msg.errorMessage = e?.message || '问答服务暂不可用'
      msg.errorData = e?.data ?? null
    }
    return msg
  }
  function clear() {
    messages.value = []
    sessionId.value = null
  }
  return { sessionId, messages, ask, clear, ensureSession }
})
