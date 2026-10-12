// Verified recording prefix followed by normal model-driven continuation.
// All generated sources, stores and ledgers stay under explicit ignored __data3 output.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {execFileSync,spawn} from 'node:child_process';
import {chromium} from 'playwright-core';
import {normalizeState,replayInBrowser,handoff,finalizeInBrowser} from './hybrid-runtime.mjs';

const root = path.resolve(import.meta.dirname, '..');
let here, id, tick, options;
const read=p=>JSON.parse(fs.readFileSync(p));
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const write=(name,value)=>{
  const file=path.join(here,name); fs.writeFileSync(file+'.tmp',JSON.stringify(value,null,2)+'\n');
  fs.renameSync(file+'.tmp',file);
};
const git=(...args)=>execFileSync('git',args,{cwd:root});
const evidence=['__data1/agent-traces.json','__data1/recordings.json','__data1/trace-cohorts.json'];
const hashes=files=>Object.fromEntries(files.map(p=>[p,hash(fs.readFileSync(path.join(root,p)))]));
const status=()=>fs.existsSync(path.join(here,'state.json'))?read(path.join(here,'state.json')):null;
const backendUrl='http://127.0.0.1:8485';
let viteUrl;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function ready(url){try{return (await fetch(url,{signal:AbortSignal.timeout(2000)})).ok;}catch{return false;}}
async function stopOwned(child){
  if(!child||child.exitCode!==null||child.signalCode!==null) return;
  if(child.ownedGroup)process.kill(-child.pid,'SIGTERM');else child.kill('SIGTERM');
  await Promise.race([new Promise(resolve=>child.once('exit',resolve)),sleep(5000)]);
  if(child.exitCode===null&&child.signalCode===null) {
    if(child.ownedGroup)process.kill(-child.pid,'SIGKILL');else child.kill('SIGKILL');
    await new Promise(resolve=>child.once('exit',resolve));
  }
}
async function startServer(command,args,cwd,url,logName){
  const fd=fs.openSync(path.join(here,logName),'a');
  const child=spawn(command,args,{cwd,detached:process.platform!=='win32',
    env:{...process.env,AGENT_DEBUG_LOG:'0'},stdio:['ignore',fd,fd]});
  child.ownedGroup=process.platform!=='win32';
  fs.closeSync(fd);
  for(let n=0;n<150;n++){
    if(child.exitCode!==null) throw Error(`Owned service exited; see ${logName}`);
    if(await ready(url)) return child;
    await sleep(200);
  }
  await stopOwned(child); throw Error(`Service readiness timeout: ${logName}`);
}

function prepare(){
  assert(!status(),'Existing experiment state: inspect/resume; do not rebuild');
  const traces=read(path.join(root,evidence[0])),recordings=read(path.join(root,evidence[1]));
  const catalog=read(path.join(root,evidence[2]));
  assert.equal(traces.version,4); assert.equal(recordings.version,1);
  const matches=Object.keys(traces.runs).filter(key=>key.startsWith(options.trace));
  assert.equal(matches.length,1,'Trace prefix must identify exactly one cataloged run');
  id=matches[0];tick=options.tick;
  const run=traces.runs[id], record=recordings.records[id];
  assert(run&&record&&catalog.traces[id]);
  assert.equal(run.playData,1);assert.equal(run.level,1);
  assert(run.steps.every(step=>!step.state.godMode),'Only normal Classic 1:1 is supported');
  assert.equal(record.traceId,id);
  const prefix=run.steps.filter(s=>s.state.tick<tick);
  assert.equal(run.steps[prefix.length].state.tick,tick);
  const controlRevision=git('rev-parse','--verify',`${options.controlRef}^{commit}`).toString().trim();
  const controlFiles=git('ls-tree','-r','--name-only',controlRevision,'app.py','agent','public/agent-config.json','public/LLM_GAME_RULES.md').toString().trim().split('\n').filter(n=>/\.(py|json|md)$/.test(n));
  const files=['app.py','public/agent-config.json','public/LLM_GAME_RULES.md',
    ...fs.readdirSync(path.join(root,'agent')).filter(n=>/\.(py|json)$/.test(n)).map(n=>'agent/'+n)];
  const manifest={traceId:id,forkTick:tick,historicalProvenance:catalog.traces[id],
    currentSource:{revision:git('rev-parse','HEAD').toString().trim(),
      dirtyFingerprint:hash(git('diff','HEAD','--binary')),sourceHashes:hashes(files)},
    evidenceHashes:hashes(evidence),prefixDecisions:prefix.length,paidCeiling:options.paidBudget,
    model:run.model.name,profile:run.model.profile,controlRef:options.controlRef,controlRevision,
    historyLimit:read(path.join(root,'public/agent-config.json')).agent.historyLimit,
    browser:options.browser,baseUrl:options.baseUrl,arms:{},createdAt:new Date().toISOString()};
  manifest.toolHashes=hashes(['scripts/hybrid-reproducer.mjs','scripts/hybrid-runtime.mjs']);
  for(const arm of ['control','fix']){
    const dir=path.join(here,'arms',arm);fs.mkdirSync(path.join(dir,'public'),{recursive:true});
    fs.mkdirSync(path.join(dir,'agent'),{recursive:true});fs.mkdirSync(path.join(dir,'__data1'),{recursive:true});
    const armFiles=arm==='control'?controlFiles:files;
    for(const name of armFiles){
      const bytes=arm==='control'
        ?git('show',`${controlRevision}:${name}`):fs.readFileSync(path.join(root,name));
      fs.writeFileSync(path.join(dir,name),bytes,{flag:'wx'});
    }
    // Reuse existing environments and credentials without copying their contents.
    for(const name of ['.venv','.env','.env.local']){
      if(fs.existsSync(path.join(root,name)))fs.symlinkSync(path.join(root,name),path.join(dir,name));
    }
    manifest.arms[arm]={root:dir,hashes:Object.fromEntries(armFiles.map(n=>[n,hash(fs.readFileSync(path.join(dir,n)))]))};
  }
  write('input.json',{run,record,prefix});write('manifest.json',manifest);
  write('state.json',{status:'prepared',attempts:[],paidStarted:0,updatedAt:new Date().toISOString()});
  console.log('Prepared frozen control/fix arms; zero model calls.');
}


function verifyHandoff(result,input){
  const steps=input.run.steps.filter(s=>s.state.tick>0&&s.state.tick<tick);
  assert.deepEqual(normalizeState(result.initialState,true),normalizeState(input.run.steps[0].state));
  assert.equal(result.prefixStates.length,steps.length);
  for(let i=0;i<steps.length;i++)assert.deepEqual(normalizeState(result.prefixStates[i],true),normalizeState(steps[i].state));
  assert.deepEqual(normalizeState(result.before,true),normalizeState(input.run.steps[input.prefix.length].state));
  assert.deepEqual(normalizeState(result.after,true),normalizeState(result.before,true));
  assert.equal(result.nativeMode,true);assert.equal(result.after.active,true);
  const manifest=read(path.join(here,'manifest.json'));
  assert.equal(result.history.length,Math.min(manifest.historyLimit,input.prefix.length));
  const old=input.run.steps[input.prefix.length].recentProgress?.entries ?? [];
  for(let i=0;i<old.length;i++){
    const h=result.history.slice(-old.length)[i], o=old[i];
    assert.equal(h.candidateId,o.candidateId);assert.equal(h.keyCode,o.keyCode);assert.equal(h.ticks,o.ticks);
    for(const side of ['before','after'])for(const f of ['x','y','xOffset','yOffset'])assert.equal(h[side].runner[f],o[side][f]);
    assert.equal(h.after.goldCount-h.before.goldCount,o.goldCountDelta);
  }
}

async function withPage(callback){
  let vite,browser;
  try{
    if(!await ready(viteUrl))vite=await startServer('npm',['run','dev','--','--host','0.0.0.0'],root,viteUrl,'vite.log');
    browser=await chromium.launch({executablePath:options.browser,headless:true,chromiumSandbox:true});
    const page=await browser.newPage({serviceWorkers:'block'});
    await page.goto(viteUrl,{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.lodeRunnerAgentHooks?.isReady(),null,{timeout:60000});
    return await callback(page);
  }finally{await browser?.close();await stopOwned(vite);}
}

async function preflight(){
  const input=read(path.join(here,'input.json')),manifest=checkFrozen();
  assert.equal(status().paidStarted,0,'Do not replace paid-run preflight evidence');
  const result=await withPage(page=>page.evaluate(handoff,{demo:input.record.demo,run:input.run,forkTick:tick,historyLimit:manifest.historyLimit}));
  write('handoff.json',result);verifyHandoff(result,input);
  for(const arm of ['control','fix']){
    const source=manifest.arms[arm].root;
    const payload={snapshot:result.after,history:result.history};write(`${arm}-preflight-input.json`,payload);
    const code=`import json,sys,types; from pathlib import Path; p=types.ModuleType('_check'); p.__path__=[str(Path.cwd()/'agent')];sys.modules['_check']=p; from _check.candidates import generate_candidates; from _check.config import reload_dotenv_files,resolve_model_profile,load_public_agent_config; reload_dotenv_files(); m=resolve_model_profile(sys.argv[2],source='preflight'); d=json.load(open(sys.argv[1])); pool,a=generate_candidates(d['snapshot'],d['history']);print(json.dumps({'model':m.model,'profile':m.profile,'provider':m.provider,'config':load_public_agent_config(),'candidates':[{'id':c['id'],'kind':c['kind'],'action':c['firstAction']} for c in pool]}))`;
    const out=JSON.parse(execFileSync(path.join(root,'.venv/bin/python'),['-B','-c',code,path.join(here,`${arm}-preflight-input.json`),manifest.profile],{cwd:source}));
    assert.equal(out.model,manifest.model);assert.equal(out.profile,manifest.profile);
    assert.deepEqual(out.config.backend,input.run.config);
    assert(out.candidates.length,'Candidate pool must be nonempty');
    assert.equal(out.config.agent.historyLimit,manifest.historyLimit);
    assert(out.config.agent.maxSteps>input.prefix.length,'Prefix exhausted the configured decision limit');
    write(`${arm}-preflight.json`,out);
  }
  assert.deepEqual(hashes(evidence),manifest.evidenceHashes);
  write('preflight.json',{status:'passed',prefixDecisions:input.prefix.length,
    matchingHistoricalPrefixDecisions:result.prefixStates.length+1,forkStateMatched:true,
    historyEntries:result.history.length,
    modelCalls:0,guardFuture:'native PLAY_MODERN',originalEvidencePreserved:true,
    checkedAt:new Date().toISOString()});
  const s=status();s.status='preflight-passed';s.updatedAt=new Date().toISOString();write('state.json',s);
  console.log('Prefix, native handoff, history and both model-free candidate pools passed.');
}

function checkFrozen(){
  const manifest=read(path.join(here,'manifest.json'));
  assert.deepEqual(hashes(Object.keys(manifest.toolHashes)),manifest.toolHashes,'Reproducer changed after preparation');
  assert.deepEqual(hashes(evidence),manifest.evidenceHashes,'Original evidence changed');
  if(manifest.frontendHashes)assert.deepEqual(hashes(Object.keys(manifest.frontendHashes)),manifest.frontendHashes,'Frontend/runtime changed');
  for(const arm of Object.values(manifest.arms))for(const [name,expected]of Object.entries(arm.hashes))
    assert.equal(hash(fs.readFileSync(path.join(arm.root,name))),expected,`Frozen source changed: ${name}`);
  return manifest;
}

async function trial(arm,pair,fake=false){
  const manifest=checkFrozen(), input=read(path.join(here,'input.json'));
  assert.equal(read(path.join(here,'preflight.json')).status,'passed');
  if(await ready(backendUrl+'/api/health'))throw Error('Existing Flask backend: ask its owner to stop it; never reuse it');
  const label=fake?`smoke-${arm}`:`pair-${pair}-${arm}`;
  const dir=path.join(here,label);fs.mkdirSync(dir);fs.mkdirSync(path.join(dir,'__data1'));
  const runId=crypto.randomUUID(), ownerRoute='/__reproducer_owner_'+runId;
  const item={label,arm,pair,fake,runId,status:'preparing',pid:process.pid,modelRequests:0,
    startedAt:new Date().toISOString(),directory:dir,continuationStartTick:tick};
  let backend;
  const persist=()=>{
    write(`${label}/result.json`,item);
    if(!fake){const s=status();const i=s.attempts.findIndex(a=>a.runId===runId);
      if(i<0)s.attempts.push(item);else s.attempts[i]=item;
      s.updatedAt=new Date().toISOString();write('state.json',s);}
  };
  try{
    let code=`import app; from pathlib import Path; app.STORE_PATH=Path(${JSON.stringify(path.join(dir,'__data1/recordings.json'))}); app.TRACE_STORE_PATH=Path(${JSON.stringify(path.join(dir,'__data1/agent-traces.json'))}); app.app.add_url_rule(${JSON.stringify(ownerRoute)},'reproducer_owner',lambda:{'id':${JSON.stringify(runId)}}); `;
    code+=`from flask import request,jsonify; app.app.before_request(lambda:(jsonify({'error':'isolated reproducer: foreign writes disabled'}),403) if request.method not in ('GET','HEAD','OPTIONS') and ((request.get_json(silent=True) or {}).get('runId') or (request.get_json(silent=True) or {}).get('traceId'))!=${JSON.stringify(runId)} else None); `;
    if(fake)code+=`import json; from types import SimpleNamespace as N; import agent.service as service; service.AisuiteAgentClient.create_completion=lambda self,model,messages,**kwargs:N(choices=[N(message=N(content=json.dumps({'candidateId':json.JSONDecoder().raw_decode(messages[-1]['content'].split('Decision context (valid JSON):\\n',1)[1])[0]['candidates'][0]['id'],'reasoning':'model-free integration smoke'})))],id='fake-model-free',created=0); `;
    code+="app.app.run(host='0.0.0.0',port=8485,use_reloader=False)";
    backend=await startServer(path.join(root,'.venv/bin/python'),['-u','-c',code],manifest.arms[arm].root,
      backendUrl+ownerRoute,`${label}/backend.log`);
    item.backendPid=backend.pid;persist();
    const result=await withPage(async page=>{
      const setup=await page.evaluate(handoff,{demo:input.record.demo,run:input.run,forkTick:tick,historyLimit:manifest.historyLimit});
      verifyHandoff(setup,input);write(`${label}/handoff.json`,setup);
      assert.deepEqual(setup.history,read(path.join(here,'handoff.json')).history);
      if(!fake){
        const s=status();assert(s.paidStarted<manifest.paidCeiling,'Paid ceiling reached');
        s.paidStarted++;s.status='running';s.activeRunId=runId;write('state.json',s);
      }
      item.status=fake?'running-model-free':'running-paid';persist();
      const config=read(path.join(manifest.arms[arm].root,'public/agent-config.json'));
      const observations=[];let planner;
      const deadline=Date.now()+60*60*1000;
      const max=fake?1:config.agent.maxSteps-input.prefix.length;
      for(let n=0;n<max;n++){
        if(Date.now()>deadline)throw Error('Continuation wall timeout after 60 minutes');
        const before=await page.evaluate(()=>window.lodeRunnerAgentHooks.snapshot());
        if(['runner_dead','finish'].includes(before.gameStateName))break;
        assert.equal(before.playMode,setup.after.playMode,'Continuation left native PLAY_MODERN');
        const history=await page.evaluate(()=>window.__targetedContinuation.history);
        item.modelRequests++;item.lastTick=before.tick;persist();
        const response=await fetch(backendUrl+'/api/agent/next-action',{
          method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(60*60*1000),
          body:JSON.stringify({playData:1,level:1,snapshot:before,history,runId,modelProfile:manifest.profile})});
        const body=await response.json();assert(response.ok,`Agent API ${response.status}: ${JSON.stringify(body)}`);
        assert.equal(body.planner.model,manifest.model);assert.equal(body.planner.modelProfile,manifest.profile);
        assert.deepEqual(body.planner.config,input.run.config);planner=body.planner;
        const observed=await page.evaluate(async({response,config})=>{
          const {_test}=await import('/src/agent.js'), hooks=window.lodeRunnerAgentHooks;
          const before=hooks.snapshot(),action=_test.normalizeAgentAction(response.action,config);
          hooks.step(action.keyCode,action.ticks);
          const after=hooks.getTerminalSnapshot()??hooks.snapshot();
          const history=window.__targetedContinuation.history;
          history.push({candidateId:response.candidateId,...action,tick:before.tick,state:before.gameStateName,
            afterTick:after.tick,afterState:after.gameStateName,
            before:_test.summarizeHistorySnapshot(before),after:_test.summarizeHistorySnapshot(after)});
          while(history.length>config.agent.historyLimit)history.shift();
          return {before,after,candidateId:response.candidateId,action};
        },{response:body,config});
        observations.push(observed);item.lastTick=observed.after.tick;persist();
        write(`${label}/observations.json`,observations);
        if(['runner_dead','finish'].includes(observed.after.gameStateName))break;
        if(observed.after.time>=config.agent.maxPlaybackTimeSeconds||observed.after.tick>=config.agent.maxPlaybackTimeSeconds*30)break;
      }
      const final=await page.evaluate(finalizeInBrowser);
      const solver={modelProfile:planner.modelProfile,provider:planner.provider,model:planner.model,
        generatedAt:planner.generatedAt,responseId:planner.responseId,traceId:runId,
        failureReason:final.result==='failure'?final.reason:null};
      const saved=await fetch(backendUrl+'/api/recordings/1/1',{
        method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({
          demo:final.demo,source:'agent',result:final.result,solver,traceId:runId,finalSnapshot:final.snapshot})});
      assert(saved.ok,'Recording persistence failed');
      return {...final,observations:observations.length,record:await saved.json()};
    });
    const trace=read(path.join(dir,'__data1/agent-traces.json')).runs[runId];
    assert.equal(trace.steps.length,result.observations);assert.equal(trace.steps[0].state.tick,tick);
    assert(trace.steps[0].candidates.some(c=>c.id===trace.steps[0].decision.selectedId),'First selection must be exposed');
    assert.equal(trace.outcome.finalState.tick,result.snapshot.tick);
    assert(result.record.demo.bornPos.every(Number.isInteger),'Malformed recorded respawn coordinates');

    item.status='completed';item.result=result.result;item.reason=result.reason;
    item.finalTick=result.snapshot.tick;item.gameTime=result.snapshot.time;
    item.goldCollected=input.run.steps[input.prefix.length].state.gold.remainingCount-result.snapshot.gold.remainingCount;
    item.steps=result.observations;item.firstSelected=trace.steps[0].decision.selectedId;
    item.executedDigs=trace.steps.filter(s=>[88,90].includes(s.action.keyCode)).length;
    item.movementSteps=trace.steps.filter(s=>[37,38,39,40].includes(s.action.keyCode)).length;
    item.finalState=result.snapshot;item.finishedAt=new Date().toISOString();
    write(`${label}/recording.json`,result.record);checkFrozen();persist();
    console.log(`${label}: ${item.reason}, ${item.steps} decisions, tick ${item.finalTick}`);
  }catch(error){
    item.status='failed';item.error=error.stack;persist();
    const state=status();state.status='failed';state.activeRunId=null;write('state.json',state);
    throw error;
  }
  finally{await stopOwned(backend);}
  return item;
}

async function pair(number){
  assert(Number.isInteger(number)&&number>=1);
  const s=status();assert(['preflight-passed','awaiting-pair-review'].includes(s.status));
  assert(number*2<=read(path.join(here,'manifest.json')).paidCeiling,'Pair exceeds the frozen paid budget');
  if(number>1)assert((s.reviewedPairs||[]).includes(number-1),'Review the prior pair first');
  assert.equal(read(path.join(here,'smoke-verification.json')).status,'passed');
  assert.equal(s.attempts.length,(number-1)*2,'Review prior attempts before resuming');
  if(!read(path.join(here,'manifest.json')).frontendHashes){
    assert.equal(s.paidStarted,0,'Freeze runtime before paid calls');
    const manifest=read(path.join(here,'manifest.json'));
    const app=fs.readFileSync(path.join(root,'src/app.js'),'utf8');
    const legacy=[...app.match(/const legacyScripts = \[([\s\S]*?)\];/)[1].matchAll(/"(\/game\/[^"\n]+)"/g)].map(m=>'public'+m[1]);
    manifest.frontendHashes=hashes(['src/app.js','src/agent.js','src/recording.js',...legacy]);
    manifest.toolHash=hash(fs.readFileSync(import.meta.filename));write('manifest.json',manifest);
  }
  const fd=fs.openSync(path.join(here,'runner.lock'),'wx');
  fs.writeFileSync(fd,JSON.stringify({pid:process.pid,pair:number}));fs.closeSync(fd);
  try{
    const results=[];
    for(const arm of number%2?['control','fix']:['fix','control'])results.push(await trial(arm,number));
    write(`pair-${number}-comparison.json`,{results,limit:'Targeted stochastic continuations; no general success-rate inference'});
    const state=status();state.status='awaiting-pair-review';state.activeRunId=null;write('state.json',state);
  }finally{
    const lock=read(path.join(here,'runner.lock'));assert.equal(lock.pid,process.pid);
    fs.unlinkSync(path.join(here,'runner.lock'));
  }
}

async function verifySmoke(){
  const input=read(path.join(here,'input.json')),verified=[];
  for(const arm of ['control','fix']){
    const folder=path.join(here,`smoke-${arm}`), result=read(path.join(folder,'result.json'));
    assert.equal(result.fake,true);assert.equal(result.status,'completed');
    const recording=read(path.join(folder,'recording.json'));
    const trace=read(path.join(folder,'__data1/agent-traces.json')).runs[result.runId];
    const replay=await withPage(page=>page.evaluate(replayInBrowser,{demo:recording.demo}));
    const states=new Map(replay.states.map(s=>[s.tick,s]));
    for(const step of [...input.prefix,...trace.steps]){
      const engine=step.state.tick===0?replay.initialState:states.get(step.state.tick);
      assert.deepEqual(normalizeState(engine,true),normalizeState(step.state),`${arm}:${step.state.tick}`);
    }
    assert.deepEqual(normalizeState(states.get(result.finalTick),true),normalizeState(result.finalState,true));
    verified.push({arm,prefixMatched:input.prefix.length,continuationMatched:trace.steps.length,
      finalTickMatched:result.finalTick,modelCalls:0});
  }
  write('smoke-verification.json',{status:'passed',verified,paidStarted:status().paidStarted});
  console.log('Both generated smoke recordings replay the prefix, continuation and final state exactly.');
}

export const usage = `npm run eval:reproduce -- <command> --output __data3/<experiment>
Commands: prepare, preflight, smoke, verify-smoke, pair N, review, finish, status
prepare requires --trace ID_OR_PREFIX --tick N
Prepare options: --control-ref REF (HEAD), --paid-budget N (0; even, maximum 100),
          --browser PATH (/usr/bin/chromium), --base-url URL (http://127.0.0.1:8283/)`;

export function parseArgs(args) {
  if (args.length === 1 && args[0] === '--help') return { help: true };
  const commands = new Set(['prepare','preflight','smoke','verify-smoke','pair','review','finish','status']);
  const result = { command: args[0], controlRef: 'HEAD', paidBudget: 0,
    browser: '/usr/bin/chromium', baseUrl: 'http://127.0.0.1:8283/' };
  assert(commands.has(result.command), usage);
  let index = 1;
  if (result.command === 'pair') {
    result.pair = Number(args[index++]);
    assert(Number.isInteger(result.pair) && result.pair > 0, 'Pair number must be a positive integer');
  }
  const names = { '--output':'output', '--trace':'trace', '--tick':'tick',
    '--control-ref':'controlRef', '--paid-budget':'paidBudget', '--browser':'browser', '--base-url':'baseUrl' };
  const seen = new Set();
  while (index < args.length) {
    const flag = args[index++], key = names[flag], value = args[index++];
    assert(key && value && !value.startsWith('--') && !seen.has(key), 'Unknown, missing or duplicate option: '+flag);
    if (result.command !== 'prepare') assert(key==='output', 'Target, runtime and budget are frozen at prepare');
    result[key] = value; seen.add(key);
  }
  assert(result.output, '--output is required');
  result.output = path.resolve(root, result.output);
  assert(result.output.startsWith(path.join(root,'__data3')+path.sep), 'Output must be a subdirectory of ignored __data3');
  result.browser = path.resolve(result.browser);
  const url = new URL(result.baseUrl);
  assert(['localhost','127.0.0.1','[::1]'].includes(url.hostname), 'Frontend must be local');
  result.baseUrl = url.href;
  if (result.command === 'prepare') {
    assert(result.trace, '--trace is required');
    result.tick = Number(result.tick);
    assert(Number.isInteger(result.tick) && result.tick > 0, '--tick must be a positive integer decision boundary');
    result.paidBudget = Number(result.paidBudget);
    assert(Number.isInteger(result.paidBudget) && result.paidBudget >= 0 &&
      result.paidBudget <= 100 && result.paidBudget % 2 === 0, '--paid-budget must be even, 0..100');
  }
  return result;
}

export async function main(args = process.argv.slice(2)) {
  options = parseArgs(args);
  if (options.help) { console.log(usage); return; }
  here = options.output; viteUrl = options.baseUrl;
  const command = options.command;
  if (command === 'prepare') {
    assert(!fs.existsSync(here), 'Choose a fresh output directory; existing evidence is never overwritten');
    fs.mkdirSync(here, { recursive: true });
    prepare();
    return;
  }
  const manifest = read(path.join(here,'manifest.json'));
  id = manifest.traceId; tick = manifest.forkTick;
  options.browser = manifest.browser; viteUrl = manifest.baseUrl;
  if (command === 'status') { console.log(JSON.stringify(status(),null,2)); return; }
  assert(!fs.existsSync(path.join(here,'runner.lock')), 'A runner lock exists: inspect its owner; do not duplicate or remove it blindly');
  if (['preflight','smoke','verify-smoke','pair'].includes(command))
    assert(!['complete','failed'].includes(status().status), 'Experiment is terminal; preserve it and choose a new output');
  if (command === 'preflight') await preflight();
  else if (command === 'smoke') {
    for (const arm of ['control','fix']) {
      const file = path.join(here,`smoke-${arm}/result.json`);
      if (fs.existsSync(file)) {
        const result = read(file);
        assert(result.fake && result.status === 'completed', 'Inspect a failed smoke before retry');
        console.log(`smoke-${arm}: reusing completed evidence`);
      } else await trial(arm,0,true);
    }
  } else if (command === 'verify-smoke') await verifySmoke();
  else if (command === 'pair') await pair(options.pair);
  else if (command === 'review') {
    const state = status();
    assert.equal(state.status,'awaiting-pair-review');
    assert(state.attempts.every(a=>a.status==='completed'), 'Inspect failed attempts first');
    const number = Math.max(...state.attempts.map(a=>a.pair));
    console.log(JSON.stringify(read(path.join(here,`pair-${number}-comparison.json`)),null,2));
    state.reviewedPairs = [...new Set([...(state.reviewedPairs||[]),number])];
    write('state.json',state);
  } else if (command === 'finish') {
    const state = status();
    assert.equal(state.status,'awaiting-pair-review');
    const number = Math.max(...state.attempts.map(a=>a.pair));
    assert((state.reviewedPairs||[]).includes(number), 'Review the latest pair before finishing');
    state.status='complete'; state.finishedAt=new Date().toISOString();write('state.json',state);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === import.meta.filename) {
  try { await main(); } catch (error) { console.error(error.stack); process.exitCode=1; }
}

