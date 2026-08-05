import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Nur für lokales `npm run dev` außerhalb von Docker - im gebauten Image wird das
    // Frontend vom selben FastAPI-Prozess ausgeliefert wie /api, kein Proxy nötig.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
})
