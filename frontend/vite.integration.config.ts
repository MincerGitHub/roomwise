import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// Playwright starts both servers with a temporary runtime and disabled providers.
// The normal application configuration keeps ports 5173 / 8765.
const target=process.env.ROOMWISE_E2E_API_URL||'http://127.0.0.1:18766';
const proxy={'/api':target,'/uploads':target};
export default defineConfig({plugins:[react()],server:{port:Number(process.env.ROOMWISE_E2E_WEB_PORT||15173),strictPort:true,proxy}});
