'use strict';
// Extend the existing Express API. No separate HTTP server or state store.
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');

function install(app) {
  const root=process.env.EXPLOREOS_ROOT, python=process.env.EXPLOREOS_PYTHON;
  if(!root||!python||!fs.existsSync(path.join(root,'explore/native.py')))
    throw new Error('ExploreOS requires the configured checkout and Python');
  const packageRoot=path.dirname(require.resolve('clawinstitute/package.json',{paths:[path.join(root,'.runtime/clawinstitute')]}));
  const express=require(require.resolve('express',{paths:[packageRoot]}));
  const {requireAuth}=require(path.join(packageRoot,'src/middleware/auth.js'));
  const api=express.Router(),active=new Map();
  const allowed=new Set(['pause','resume','cancel','steer','challenge','assess','reconcile','retry','extend','advance','add-source','link-memory','configure-execution']);
  function headers(res){
    res.set('Cache-Control','no-store');res.set('X-Content-Type-Options','nosniff');
    res.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'");
  }
  // Next's existing /api/v1 rewrite keeps this on the native UI/login origin.
  app.get('/api/v1/exploreos/ui',(req,res)=>{headers(res);res.sendFile(path.join(root,'explore/web/index.html'));});
  app.get('/api/v1/exploreos/assets/:name',(req,res)=>{
    if(!['app.js','style.css'].includes(req.params.name))return res.sendStatus(404);
    headers(res);res.sendFile(path.join(root,'explore/web',req.params.name));
  });
  api.use(requireAuth);
  api.use((req,res,next)=>{
    headers(res);
    if(!/^(127\.0\.0\.1|localhost|\[::1\]):\d+$/.test(req.headers.host||''))return res.sendStatus(403);
    const origin=req.headers.origin;
    if(origin){
      let address;try{address=new URL(origin);}catch{return res.sendStatus(403);}
      const ports=[String(process.env.PORT||3000),String(process.env.CLAWINSTITUTE_FRONTEND_PORT||3001)];
      if(address.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(address.hostname)||!ports.includes(address.port))
        return res.status(403).json({error:'Cross-origin project controls are disabled'});
    }
    next();
  });
  function run(payload,response,background=false){
    const encoded=JSON.stringify(payload);
    if(Buffer.byteLength(encoded)>96000)return response.status(400).json({error:'Use a smaller control request'});
    const child=spawn(python,['-m','explore.native'],{cwd:root,env:process.env,stdio:['pipe','pipe','pipe']});
    let output='';child.stdin.on('error',()=>{});child.stdin.end(encoded);child.stderr.resume();
    if(background){
      active.set(payload.name,child);child.stdout.resume();
      child.on('error',()=>active.delete(payload.name));child.on('exit',()=>active.delete(payload.name));
      return response.status(202).json({accepted:true,qualification:'Existing Project claims determine actual execution'});
    }
    const timeout=setTimeout(()=>child.kill('SIGTERM'),45000);
    child.stdout.on('data',chunk=>{output+=chunk;if(Buffer.byteLength(output)>32*1024*1024)child.kill('SIGTERM');});
    child.on('error',()=>{clearTimeout(timeout);if(!response.headersSent)response.status(503).json({error:'Native controller could not start'});});
    child.on('close',()=>{
      clearTimeout(timeout);if(response.headersSent)return;
      try{
        const result=JSON.parse(output);
        if(!result.ok)return response.status(result.error_type==='Conflict'?409:400).json({error:result.error,error_type:result.error_type});
        if(payload.action==='export')response.set('Content-Disposition',`attachment; filename="${payload.name}-export.json"`);
        response.json(result.data);
      }catch{response.status(503).json({error:'Native controller result unavailable; inspect state before retrying'});}
    });
  }
  api.get('/projects',(req,res)=>run({action:'projects'},res));
  api.get('/runtime',(req,res)=>run({action:'runtime'},res));
  api.post('/projects',(req,res)=>run({action:'create',data:req.body},res));
  api.get('/project/:name/audit/:target',(req,res)=>run({action:'audit',name:req.params.name,target:req.params.target},res));
  api.get('/project/:name/:view',(req,res)=>{
    if(!['state','export','brief'].includes(req.params.view))return res.sendStatus(404);
    run({action:req.params.view,name:req.params.name},res);
  });
  api.post('/project/:name/:action',(req,res)=>{
    const {name,action}=req.params;
    if(!/^[a-z0-9_]{1,24}$/.test(name)||!allowed.has(action))return res.sendStatus(400);
    if(action==='advance'&&!['simulated','pi','pi-subagents','claude'].includes(req.body?.backend||'simulated'))
      return res.status(400).json({error:'Choose a supported execution backend'});
    if(action==='advance'&&active.has(name))return res.status(409).json({error:'An owned advance is already queued; inspect project state'});
    run({action,name,data:req.body},res,action==='advance');
  });
  app.use('/api/v1/exploreos',api);
}
module.exports={install};
