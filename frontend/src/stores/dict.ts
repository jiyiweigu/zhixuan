import { defineStore } from 'pinia'
import { ref } from 'vue'
export const useDictStore=defineStore('dict',()=>{const provinces=ref(['河南','江西','河北','山东','山西']);const pathways=ref<any[]>([]);return{provinces,pathways}})
