import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/  （Vite 配置文档）
// 本地开发时，后端 Worker（wrangler dev）的地址。
// 用 127.0.0.1 而不是 localhost：Node 18+ 会把 localhost 优先解析成 ::1，
// 而 wrangler dev 默认只监听 IPv4，直接用 localhost 会得到 ECONNREFUSED。
const WORKER_ORIGIN = process.env.VITE_WORKER_ORIGIN ?? 'http://127.0.0.1:8787'

export default defineConfig({
  plugins: [react()],
  // 静态数据（/data/panda/*、/data/*.json）只在仓库根目录的 public/ 里保存一份。
  // 生产环境由 Worker 的 ASSETS 绑定提供，开发环境由 Vite 从这里提供，
  // 避免在 frontend/ 下再复制一份模型文件。
  publicDir: '../public',
  optimizeDeps: {
    // mujoco-react 需要排除预构建，否则会破坏 WASM 动态导入
    exclude: ['mujoco-react', 'mujoco-js'],
  },
  server: {
    port: 5173,
    strictPort: true, // 端口被占用时直接报错，不自动递增
    headers: {
      // WebGPU 多线程需要跨域隔离头
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
    proxy: {
      // 页面默认请求同源的 /api 与 /ws（见 src/App.tsx），
      // 开发时需要转发到 wrangler dev，否则会打到 5173 上得到 404。
      '/api': {
        target: WORKER_ORIGIN,
        changeOrigin: true,
      },
      '/ws': {
        target: WORKER_ORIGIN,
        changeOrigin: true,
        ws: true, // 必须开启，否则 WebSocket 升级不会被代理
      },
    },
  },
})
