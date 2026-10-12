import { defineStore } from 'pinia'
import { ref } from 'vue'
export const useQaStore=defineStore('qa',()=>{const sessionId=ref<string|null>(null);const messages=ref<any[]>([]);function add(m:any){messages.value.push(m);if(m.session_id)sessionId.value=m.session_id}function clear(){messages.value=[];sessionId.value=null}return{sessionId,messages,add,clear}})
