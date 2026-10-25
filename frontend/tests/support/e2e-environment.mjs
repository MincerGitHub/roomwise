// Browser regressions always own their servers and their database. An arbitrary
// base URL could silently send destructive tests to the user's running app.
if(process.env.ROOMWISE_E2E_BASE_URL){
 throw new Error('ROOMWISE_E2E_BASE_URL is no longer supported. Use ROOMWISE_E2E_WEB_PORT and ROOMWISE_E2E_API_PORT for isolated test servers.');
}

function testPort(name,fallback){
 const value=process.env[name]??String(fallback);
 const port=Number(value);
 if(!/^\d+$/.test(value)||!Number.isInteger(port)||port<1024||port>65535||[5173,8765].includes(port)){
  throw new Error(`${name} must be an unused test port from 1024 to 65535, excluding application ports 5173 and 8765.`);
 }
 return port;
}

export const frontendPort=testPort('ROOMWISE_E2E_WEB_PORT',15173);
export const backendPort=testPort('ROOMWISE_E2E_API_PORT',18766);
if(frontendPort===backendPort)throw new Error('The isolated frontend and backend need different ports.');
export const frontendUrl=`http://127.0.0.1:${frontendPort}`;
export const backendUrl=`http://127.0.0.1:${backendPort}`;
