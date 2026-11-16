import { mergeConfig } from 'vite'
import baseConfig from './vite.config.ts'

// Keep the API on the same private origin as the UI when accessed through Tailscale Serve.
export default mergeConfig(baseConfig, {
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true },
    },
  },
})
