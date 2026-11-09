import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// Independent static entry: never imports the live application or its environment.
export default defineConfig({
  root: fileURLToPath(new URL('./showcase', import.meta.url)),
  base: './',
  publicDir: false,
  envDir: fileURLToPath(new URL('./showcase/no-environment-files', import.meta.url)),
  envPrefix: 'SHOWCASE_UNUSED_PUBLIC_',
  plugins: [react()],
  build: { outDir: '../dist-showcase', emptyOutDir: true, sourcemap: false, modulePreload: false },
})
