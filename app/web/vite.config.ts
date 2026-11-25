import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  build: { outDir: 'dist', assetsDir: 'assets', target: 'es2022', cssCodeSplit: false, sourcemap: false,
           modulePreload: { polyfill: false }, reportCompressedSize: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8090', '/stream': 'http://127.0.0.1:8090', '/img': 'http://127.0.0.1:8090' } },
})
