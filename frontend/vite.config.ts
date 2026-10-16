import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
const proxy={'/api':'http://127.0.0.1:8765','/uploads':'http://127.0.0.1:8765'};
export default defineConfig({plugins:[react()],server:{port:5173,strictPort:true,proxy},preview:{port:5173,strictPort:true,proxy}});
