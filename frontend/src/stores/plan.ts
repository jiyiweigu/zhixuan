import { defineStore } from 'pinia'
import { ref } from 'vue'
export const usePlanStore=defineStore('plan',()=>{const draft=ref<any>(null);const plans=ref<any[]>([]);function setDraft(v:any){draft.value=v}return{draft,plans,setDraft}})
