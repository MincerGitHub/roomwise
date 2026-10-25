import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp,realpath,rm} from 'node:fs/promises';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {backendPort,backendUrl,frontendPort,frontendUrl} from './e2e-environment.mjs';

const frontendRoot=fileURLToPath(new URL('../..',import.meta.url));
const appRoot=path.dirname(frontendRoot);
let cleanupCurrentRun=async()=>{};

export async function globalTeardown(){await cleanupCurrentRun()}

function requireUnusedPort(port){
 return new Promise((resolve,reject)=>{
  const server=createServer();
  server.once('error',()=>reject(new Error(`Test port ${port} is occupied. Stop that test run or select another ROOMWISE_E2E_*_PORT; existing servers are never reused.`)));
  server.listen(port,'127.0.0.1',()=>server.close(resolve));
 });
}

function start(command,args,options){
 const child=spawn(command,args,{...options,windowsHide:true,stdio:['ignore','pipe','pipe']});
 const state={child,output:'',error:null};
 for(const stream of [child.stdout,child.stderr])stream?.on('data',chunk=>{state.output=(state.output+chunk.toString()).slice(-8000)});
 child.once('error',error=>{state.error=error});
 return state;
}

async function ready(url,state,cancelled){
 const deadline=Date.now()+60000;
 while(Date.now()<deadline){
  if(cancelled())throw new Error('Isolated test startup was interrupted.');
  if(state.error||state.child.exitCode!==null||state.child.signalCode!==null){
   throw new Error(`Isolated test server failed: ${state.error?.message??state.output}`);
  }
  let available=false;
  try{available=(await fetch(url,{signal:AbortSignal.timeout(1500)})).ok}catch{}
  if(cancelled())throw new Error('Isolated test startup was interrupted.');
  if(available)return;
  await new Promise(resolve=>setTimeout(resolve,200));
 }
 throw new Error(`Isolated test server did not start at ${url}.\n${state.output}`);
}

async function stop(state){
 const child=state?.child;
 if(!child?.pid||child.exitCode!==null||child.signalCode!==null)return;
 const closed=new Promise(resolve=>child.once('close',resolve));
 if(process.platform==='win32'){
  // Terminate only this run's child tree, including the Windows venv launcher.
  await new Promise(resolve=>{
   const killer=spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
   killer.once('error',resolve);killer.once('close',resolve);
  });
 }else child.kill('SIGTERM');
 let timeout;
 try{await Promise.race([closed,new Promise(resolve=>{timeout=setTimeout(resolve,5000)})])}finally{clearTimeout(timeout)}
 if(child.exitCode===null&&child.signalCode===null){child.kill('SIGKILL');await closed}
}

export default async function globalSetup(){
 await Promise.all([requireUnusedPort(backendPort),requireUnusedPort(frontendPort)]);
 const temporaryRoot=await realpath(tmpdir());
 const runtime=await mkdtemp(path.join(temporaryRoot,'roomwise-e2e-'));
 const servers=[];
 let interrupted=false,cleanupPromise;
 const handlers={};
 const cleanup=()=>cleanupPromise??=(async()=>{
  interrupted=true;
  try{
   for(const server of [...servers].reverse())await stop(server);
   // The recursive deletion target is the exact mkdtemp result inside tmpdir.
   const resolved=await realpath(runtime);
   if(path.dirname(resolved)!==temporaryRoot||!path.basename(resolved).startsWith('roomwise-e2e-'))throw new Error('Refusing to clean an unexpected test runtime path.');
   await rm(resolved,{recursive:true,force:true,maxRetries:5,retryDelay:100});
  }finally{for(const [signal,handler] of Object.entries(handlers))process.off(signal,handler)}
 })();
 cleanupCurrentRun=cleanup;
 for(const signal of ['SIGINT','SIGTERM']){
  const handler=()=>{
   const handledElsewhere=process.listeners(signal).some(listener=>listener!==handler);
   interrupted=true;
   // Playwright handles SIGINT itself. Await the same promise in global teardown
   // even when interruption happens before globalSetup has returned its callback.
   void cleanup().then(()=>{if(!handledElsewhere)process.kill(process.pid,signal)},error=>{
    console.error(`Isolated test cleanup failed: ${error.message}`);
    process.exitCode=1;if(!handledElsewhere)process.kill(process.pid,signal);
   });
  };
  handlers[signal]=handler;process.on(signal,handler);
 }
 try{
  const virtualPython=path.join(appRoot,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
  const python=process.env.ROOMWISE_E2E_PYTHON||(existsSync(virtualPython)?virtualPython:process.platform==='win32'?'python':'python3');
  const backend=start(python,['-m','uvicorn','roomwise.main:app','--app-dir',path.join(appRoot,'backend'),'--host','127.0.0.1','--port',String(backendPort)],{
   cwd:appRoot,env:{...process.env,PYTHONUNBUFFERED:'1',ROOMWISE_RUNTIME_DIR:runtime,ROOMWISE_LANGUAGE_PROVIDER:'disabled',ROOMWISE_LANGUAGE_CONFIG:path.join(runtime,'language.local.json'),ROOMWISE_LANGUAGE_ENV_FILE:path.join(runtime,'.env.language'),ROOMWISE_VISION_PROVIDER:'disabled',ROOMWISE_VISION_ENV_FILE:path.join(runtime,'.env.vision')},
  });
  servers.push(backend);await ready(`${backendUrl}/api/health`,backend,()=>interrupted);
  if(interrupted)throw new Error('Isolated test startup was interrupted.');
  const frontend=start(process.execPath,[path.join(frontendRoot,'node_modules/vite/bin/vite.js'),'--config','vite.integration.config.ts','--host','127.0.0.1'],{
   cwd:frontendRoot,env:{...process.env,BROWSER:'none',ROOMWISE_E2E_API_URL:backendUrl,ROOMWISE_E2E_WEB_PORT:String(frontendPort)},
  });
  servers.push(frontend);await ready(frontendUrl,frontend,()=>interrupted);
  return cleanup;
 }catch(error){await cleanup();throw error}
}
