import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { apiPlugin } from './server/api-plugin'

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    // Vitest uses Vite configuration, but must not migrate/lock live projects
    // or start the development API while collecting unit tests.
    ...(mode === 'test' ? [] : [apiPlugin()]),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  optimizeDeps: {
    include: [
      'style-to-js',
      'style-to-object',
      'hast-util-to-jsx-runtime',
      'react-markdown',
    ],
  },
  ssr: {
    noExternal: ['molstar'],
  },
}))
