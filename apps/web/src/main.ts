import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { useSessionStore } from '@/shared/stores/session'
import '@/shared/styles/base.css'

const app = createApp(App)
app.use(createPinia())

// 先恢复会话再安装路由：守卫在 ready=false 时会中止初始导航且不会重放，
// 带令牌刷新会白屏。restore() 内部已捕获错误，不会 reject。
const session = useSessionStore()
void session.restore().then(() => {
  app.use(router)
  app.mount('#app')
})
