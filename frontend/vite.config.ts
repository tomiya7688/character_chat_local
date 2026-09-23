import { defineConfig } from 'vite';

export default defineConfig({
  base: '/ui/',
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  build: {
    // Generated assets are included in the Python wheel, never in source commits.
    outDir: '../src/character_chat_local/webui',
    emptyOutDir: true,
    sourcemap: false,
  },
});
