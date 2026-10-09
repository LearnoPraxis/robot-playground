import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/  （Vite 配置文档）
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    // Transformers.js 和 mujoco-react 需要排除预构建，否则会破坏 WASM 动态导入
    exclude: ['@huggingface/transformers', 'mujoco-react', 'mujoco-js'],
  },
  server: {
    port: 5173,
    strictPort: true, // 端口被占用时直接报错，不自动递增
    headers: {
      // WebGPU 多线程需要跨域隔离头
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
  },
})
