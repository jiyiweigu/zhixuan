import { createRouter, createWebHistory } from 'vue-router'
import UserLayout from '../layouts/UserLayout.vue'
import AdminLayout from '../layouts/AdminLayout.vue'
import HomeView from '../views/user/HomeView.vue'
import AuthView from '../views/user/AuthView.vue'
import ProfileView from '../views/user/ProfileView.vue'
import EligibilityView from '../views/user/EligibilityView.vue'
import PathwaysView from '../views/user/PathwaysView.vue'
import QaView from '../views/user/QaView.vue'
import PlanView from '../views/user/PlanView.vue'
import SchoolsView from '../views/user/SchoolsView.vue'
import SchoolDetailView from '../views/user/SchoolDetailView.vue'
import MajorsView from '../views/user/MajorsView.vue'
import MajorDetailView from '../views/user/MajorDetailView.vue'
import CompareView from '../views/user/CompareView.vue'
import FavoritesView from '../views/user/FavoritesView.vue'
import AdminLoginView from '../views/admin/AdminLoginView.vue'
import AdminWorkspaceView from '../views/admin/AdminWorkspaceView.vue'
import { useAuthStore } from '../stores/auth'
const router=createRouter({history:createWebHistory(),routes:[
 {path:'/',component:UserLayout,children:[
  {path:'',component:HomeView,meta:{title:'首页'}},{path:'login',component:AuthView,meta:{title:'登录'}},{path:'register',component:AuthView,meta:{title:'注册'}},
  {path:'profile',component:ProfileView,meta:{auth:true,title:'考生档案'}},{path:'eligibility',component:EligibilityView,meta:{title:'资格自检'}},
  {path:'pathways',component:PathwaysView,meta:{title:'升学途径'}},{path:'pathways/:id',component:PathwaysView,props:true,meta:{title:'途径详情'}},
  {path:'qa',component:QaView,meta:{title:'政策问答'}},{path:'plan',component:PlanView,meta:{auth:true,title:'志愿方案'}},
  {path:'schools',component:SchoolsView,meta:{title:'院校库'}},{path:'schools/:id',component:SchoolDetailView,props:true,meta:{title:'院校详情'}},
  {path:'majors',component:MajorsView,meta:{title:'专业库'}},{path:'majors/:id',component:MajorDetailView,props:true,meta:{title:'专业详情'}},
  {path:'compare',component:CompareView,meta:{title:'院校对比'}},{path:'favorites',component:FavoritesView,meta:{auth:true,title:'我的收藏'}}
 ]},
 {path:'/admin/login',component:AdminLoginView,meta:{adminLogin:true,title:'管理端登录'}},
 {path:'/admin',component:AdminLayout,meta:{admin:true},children:[{path:'',redirect:'/admin/docs'},{path:':section(docs|index|review|pathways|stats)',component:AdminWorkspaceView,props:true,meta:{admin:true}}]},
 {path:'/:pathMatch(.*)*',redirect:'/'}
]})
router.beforeEach(to=>{const auth=useAuthStore(); if(to.meta.adminLogin&&auth.isAdmin)return '/admin'; if(to.meta.admin&&!auth.isAdmin)return {path:'/admin/login',query:{redirect:to.fullPath}};if(to.meta.auth&&!auth.isAuthenticated)return {path:'/login',query:{redirect:to.fullPath}}})
export default router
