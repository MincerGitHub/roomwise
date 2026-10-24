import {defineConfig,loadEnv} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({mode})=>{
 const target=loadEnv(mode,'.','ROOMWISE_').ROOMWISE_API_URL||'http://127.0.0.1:8765';
 const proxy={'/api':target,'/uploads':target};
 return {plugins:[react()],server:{port:5173,strictPort:true,proxy},preview:{port:5173,strictPort:true,proxy}};
});
