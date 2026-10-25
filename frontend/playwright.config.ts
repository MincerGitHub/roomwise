import {defineConfig} from '@playwright/test';
import {frontendUrl} from './tests/support/e2e-environment.mjs';

export default defineConfig({
 testDir:'./tests',timeout:60000,workers:1,
 globalSetup:'./tests/support/e2e-setup.mjs',
 globalTeardown:'./tests/support/e2e-teardown.mjs',
 use:{baseURL:frontendUrl,headless:true,channel:'msedge',viewport:{width:1440,height:1000},launchOptions:{args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']},screenshot:'only-on-failure',trace:'retain-on-failure'},
 reporter:[['list'],['html',{open:'never'}]],
});
