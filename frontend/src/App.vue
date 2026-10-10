<script setup lang="ts">
import { ref } from 'vue'
import { ArrowUpRight, Compass, MessageCircle, Sparkles } from 'lucide-vue-next'
const active = ref('home')
const nav = [{id:'home',label:'首页'}, {id:'profile',label:'我的档案'}, {id:'eligibility',label:'资格自检'}, {id:'qa',label:'问答'}, {id:'plan',label:'方案'}]
const stats = [{value:'26',label:'升学途径'}, {value:'3',label:'决策策略'}, {value:'100%',label:'来源可追溯'}]
</script>
<template>
  <div class="shell">
    <header class="topbar"><div class="brand"><span class="brand-mark">Z</span><span>智选志愿</span></div><nav><button v-for="item in nav" :key="item.id" :class="{active:active===item.id}" @click="active=item.id">{{item.label}}</button></nav><button class="login">登录 <ArrowUpRight :size="15"/></button></header>
    <main>
      <section class="hero"><div class="eyebrow">2026 · 河南首发</div><h1>把不确定的<br/><em>未来</em>，变成一张清晰的地图。</h1><p class="lede">智选志愿将政策、数据与个人选择放在同一张桌面上，陪你做出有依据的升学决定。</p><div class="hero-actions"><button class="primary" @click="active='eligibility'">开始资格自检 <ArrowUpRight :size="16"/></button><button class="text-btn" @click="active='qa'">先问一个问题 <MessageCircle :size="16"/></button></div></section>
      <section class="stats"> <div v-for="s in stats" :key="s.label" class="stat"><strong>{{s.value}}</strong><span>{{s.label}}</span></div><div class="stat-note">每一条结论，都附有来源、年份与核验入口。</div></section>
      <section class="grid"><article class="feature-card large"><div class="card-index">01 / 路径</div><Compass :size="26" stroke-width="1.4"/><h2>我能走哪条路？</h2><p>输入你的省份、分数与个人条件，快速筛出符合条件的专项与升学途径。</p><button class="link" @click="active='eligibility'">查看路径 <ArrowUpRight :size="15"/></button></article><article class="feature-card"><div class="card-index">02 / 问答</div><MessageCircle :size="26" stroke-width="1.4"/><h2>把问题问明白</h2><p>从政策原文到院校数据，答案附带可回溯的引用与置信度。</p><button class="link" @click="active='qa'">开始提问 <ArrowUpRight :size="15"/></button></article><article class="feature-card dark"><div class="card-index">03 / 方案</div><Sparkles :size="26" stroke-width="1.4"/><h2>生成我的志愿表</h2><p>冲、稳、保三种策略，随你的偏好调整，风险一目了然。</p><button class="link light" @click="active='plan'">探索方案 <ArrowUpRight :size="15"/></button></article></section>
      <section class="disclaimer"> <span>提示</span><p>智选志愿提供信息整理与决策辅助，最终志愿填报请以官方发布为准。</p><a href="#">查看数据来源说明 ↗</a></section>
    </main><footer><span>© 2026 智选志愿</span><span>让每一次选择，都有证据可循。</span></footer>
  </div>
</template>
