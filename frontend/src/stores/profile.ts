import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'
export const useProfileStore=defineStore('profile',()=>{const profile=ref<any>(null);const loaded=ref(false);async function load(){const p=await api.getProfile();profile.value=p;loaded.value=true}async function save(value:any){profile.value=await api.updateProfile(value);return profile.value}return{profile,loaded,load,save}})
