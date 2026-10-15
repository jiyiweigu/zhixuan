import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'
export const useProfileStore=defineStore('profile',()=>{const profile=ref<any>(null);const completeness=ref<any>(null);const loaded=ref(false);async function load(){const p:any=await api.getProfile();profile.value=p;completeness.value=p?.completeness||null;loaded.value=true;return p}async function save(value:any){const p:any=await api.updateProfile(value);profile.value=p;completeness.value=p?.completeness||null;localStorage.removeItem('eligibility_cache');localStorage.removeItem('recommendation_cache');localStorage.removeItem('risk_check_cache');return p}return{profile,completeness,loaded,load,save}})
