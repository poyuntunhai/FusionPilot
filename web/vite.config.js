import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
// The dev proxy targets are overridable so the dev server can be pointed somewhere else: a second
// local instance on another port (when 8080 is already taken by something unrelated), or a deployed
// environment. The defaults are the documented local setup, so nothing changes by default.
const javaTarget = process.env.VITE_JAVA_TARGET ?? 'http://127.0.0.1:8080';
const agentTarget = process.env.VITE_AGENT_TARGET ?? 'http://127.0.0.1:8000';
export default defineConfig({
    plugins: [vue()],
    server: {
        port: 5173,
        proxy: {
            '/api/v1/agent': {
                target: agentTarget,
                changeOrigin: true
            },
            '/api': {
                target: javaTarget,
                changeOrigin: true
            }
        }
    }
});
