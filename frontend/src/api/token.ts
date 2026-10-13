const KEY='access_token';export const getToken=()=>localStorage.getItem(KEY);export const setToken=(v:string)=>localStorage.setItem(KEY,v);export const clearToken=()=>localStorage.removeItem(KEY)
