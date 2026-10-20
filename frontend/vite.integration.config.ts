import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// Integration tests use a separate backend with language API calls disabled.
// The normal application configuration keeps port 8765.
const proxy={'/api':'http://127.0.0.1:8766','/uploads':'http://127.0.0.1:8766'};
export default defineConfig({plugins:[react()],server:{port:5173,strictPort:true,proxy}});
