import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// 공통 예제는 docs/development/v0.1/예제 데이터 원본을 직접 읽는다(복사본을 두지 않음).
const examples = fileURLToPath(new URL('../docs/development/v0.1/예제 데이터', import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@examples': examples } },
  server: {
    port: 5173,
    fs: { allow: ['..'] },
    // 백엔드(안선효)가 생기면 VITE_API_MODE=http 로 /v1 을 이 주소로 넘긴다.
    proxy: { '/v1': 'http://127.0.0.1:8000' },
  },
  test: { environment: 'node' },
})
