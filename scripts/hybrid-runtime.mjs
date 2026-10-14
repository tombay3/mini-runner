import assert from 'node:assert/strict';

const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const number = (v, label) => { assert(Number.isFinite(v), `${label}: missing/invalid number`); return v; };
const integer = (v, label) => { number(v, label); assert(Number.isInteger(v) && v >= 0, `${label}: expected nonnegative integer`); return v; };
const boolean = (v, label) => { assert.equal(typeof v, 'boolean', `${label}: missing/invalid boolean`); return v; };
const text = (v, label) => { assert(typeof v === 'string' && v.length, `${label}: missing/invalid string`); return v; };

export function verifyEngineContext(state, godMode) {
  assert.equal(state.playData, 1, 'Unsupported playData');
  assert.equal(state.level, 1, 'Unsupported level');
  assert.equal(state.godMode, godMode, 'Continuation mode mismatch');
}

export function replayStateAt(replay, tick, terminal = false) {
  // A natural terminal can share its tick with the last running observation.
  // Decision boundaries use the running observation; final verification uses
  // the actual terminal, never a synthesized phase.
  if (terminal && replay.terminal?.tick === tick) return replay.terminal;
  if (tick === 0) return replay.initialState;
  const state = replay.states.find(s => s.tick === tick);
  assert(state, `Missing replay boundary at tick ${tick}`);
  return state;
}

export function normalizeState(state, engine = false, label = 'state') {
  assert(object(state), `${label}: missing state`);
  function actor(value, name, guard = false) {
    assert(object(value), `${name}: missing actor`);
    const out = Object.fromEntries(['x', 'y', 'xOffset', 'yOffset'].map(k => [k, number(value[k], `${name}.${k}`)]));
    out.action = text(engine ? value.actionName : value.action, `${name}.action`);
    if (guard) {
      out.id = integer(value.id, `${name}.id`);
      if (engine) {
        assert(typeof value.hasGold === 'boolean' || Number.isFinite(value.hasGold), `${name}.hasGold: missing/invalid`);
        out.carryingGold = Boolean(value.hasGold);
      } else out.carryingGold = boolean(value.carryingGold, `${name}.carryingGold`);
    }
    return out;
  }
  assert(Array.isArray(state.guards), `${label}.guards: missing full guard array`);
  const guards = state.guards.map((g, i) => actor(g, `${label}.guards[${i}]`, true)).sort((a, b) => a.id - b.id);
  assert.equal(new Set(guards.map(g => g.id)).size, guards.length, `${label}: duplicate guard IDs`);
  assert(object(state.gold) && Array.isArray(state.gold.visiblePositions), `${label}.gold.visiblePositions: missing array`);
  const visiblePositions = state.gold.visiblePositions.map((p, i) => {
    assert(object(p), `${label}.gold.visiblePositions[${i}]: invalid position`);
    return { x: integer(p.x, `${label}.gold.x`), y: integer(p.y, `${label}.gold.y`) };
  }).sort((a, b) => a.y - b.y || a.x - b.x);
  assert.equal(new Set(visiblePositions.map(p => `${p.x},${p.y}`)).size, visiblePositions.length, `${label}: duplicate gold positions`);
  return {
    tick: integer(state.tick, `${label}.tick`),
    gameState: text(engine ? state.gameStateName : state.gameState, `${label}.gameState`),
    godMode: boolean(state.godMode, `${label}.godMode`),
    runner: actor(state.runner, `${label}.runner`), guards,
    gold: { remainingCount: integer(state.gold.remainingCount, `${label}.gold.remainingCount`),
      complete: boolean(state.gold.complete, `${label}.gold.complete`), visiblePositions },
  };
}
export function replayInBrowser({ demo }) {
  const w = window;
  const godMode=Boolean(demo.godMode);
  if(Boolean(w.godMode)!==godMode)w.toggleGodMode();
  w.clearIdleDemoTimer(); w.disableAutoDemoTimer(); w.disableStageClickEvent(); w.stopPlayTicker();
  w.playData = 1; w.curLevel = 1; w.levelData = w.getPlayVerData(1);
  w.playerDemoData = [demo]; w.playMode = w.PLAY_DEMO_ONCE; w.recordMode = 0;
  const originals = { playDemo: w.playDemo, getDemoGold: w.getDemoGold, getDemoBornPos: w.getDemoBornPos,
    initPlayDemo: w.initPlayDemo };
  let initialState;
  w.initPlayDemo = () => {
    // beginPlay has genuinely set GAME_START; capture before initPlayDemo sets
    // GAME_RUNNING. No phase is synthesized or assigned by this harness.
    if (w.gameState !== w.GAME_START) throw new Error('Unexpected initial demo phase');
    initialState = JSON.parse(JSON.stringify(w.lodeRunnerAgentHooks.snapshot()));
    initialState.tick = 0; // demo clock is reset to zero by the next call.
    return originals.initPlayDemo();
  };
  const inputs = new Map(), states = [];
  for (let i = 0; i < demo.action.length; i += 2) inputs.set(demo.action[i], demo.action[i + 1]);
  w.playDemo = () => { if (inputs.has(w.demoTickCount)) w.pressKey(inputs.get(w.demoTickCount)); w.demoTickCount++; };
  w.getDemoGold = guard => {
    if (w.demoGoldIdx >= demo.goldDrop.length) throw new Error('Recorded gold stream exhausted');
    return originals.getDemoGold(guard);
  };
  w.getDemoBornPos = () => {
    if (w.demoBornIdx + (demo.bornPos[0] === 2 ? 2 : 1) >= demo.bornPos.length) throw new Error('Recorded birth stream exhausted');
    return originals.getDemoBornPos();
  };
  const snapshot = () => {
    const s = w.lodeRunnerAgentHooks.snapshot(); s.tick = w.demoTickCount;
    if (s.playData !== 1 || s.level !== 1 || s.godMode!==godMode) throw new Error('Replay context/mode integrity failure');
    return JSON.parse(JSON.stringify(s));
  };
  try {
    w.startGame(1); w.stopPlayTicker();
    while (w.gameState === w.GAME_RUNNING && w.demoTickCount <= demo.time + 2) {
      states.push(snapshot());
      const before = w.demoTickCount;
      w.mainTick({ delta: 1000 / w.demoSpeed, time: before * 1000 / w.demoSpeed });
      if (w.demoTickCount <= before && w.gameState === w.GAME_RUNNING) throw new Error('Replay tick did not advance');
    }
    return { initialState, states, terminal: snapshot(), goldCursor: w.demoGoldIdx, bornCursor: w.demoBornIdx };
  } finally { Object.assign(w, originals); w.stopPlayTicker(); }
}

export async function handoff({demo,run,forkTick,historyLimit}){
  const w=window, hooks=w.lodeRunnerAgentHooks;
  const godMode=Boolean(demo.godMode);
  if(Boolean(w.godMode)!==godMode)w.toggleGodMode();
  const { _test }=await import('/src/agent.js');
  hooks.startLevel(1,1);
  w.playData=1;w.curLevel=1;w.levelData=w.getPlayVerData(1);
  w.playerDemoData=[demo];w.playMode=w.PLAY_DEMO_ONCE;w.recordMode=0;
  const old=w.playDemo, oldInit=w.initPlayDemo, oldGold=w.getDemoGold,
    oldBirth=w.getDemoBornPos, inputs=new Map(), snapshots=[];
  let initialState;
  w.initPlayDemo=()=>{
    initialState=JSON.parse(JSON.stringify(hooks.snapshot()));initialState.tick=0;
    return oldInit();
  };
  for(let i=0;i<demo.action.length;i+=2)inputs.set(demo.action[i],demo.action[i+1]);
  w.playDemo=()=>{if(inputs.has(w.demoTickCount))w.pressKey(inputs.get(w.demoTickCount));w.demoTickCount++;};
  w.getDemoGold=guard=>{
    if(w.demoGoldIdx>=demo.goldDrop.length)throw Error('Prefix gold stream exhausted');
    return oldGold(guard);
  };
  w.getDemoBornPos=()=>{
    if(w.demoBornIdx+(demo.bornPos[0]===2?2:1)>=demo.bornPos.length)throw Error('Prefix birth stream exhausted');
    return oldBirth();
  };
  const capture=()=>{const s=hooks.snapshot();s.tick=w.demoTickCount;
    if(s.playData!==1||s.level!==1||s.godMode!==godMode)throw Error('Prefix context/mode mismatch');
    return JSON.parse(JSON.stringify(s));};
  try{
    w.startGame(1);w.stopPlayTicker();
    while(w.demoTickCount<forkTick&&w.gameState===w.GAME_RUNNING){
      snapshots.push(capture());
      w.mainTick({delta:1000/w.demoSpeed,time:w.demoTickCount*1000/w.demoSpeed});
    }
    if(w.demoTickCount!==forkTick||w.gameState!==w.GAME_RUNNING)throw Error('Prefix stopped before fork');
    snapshots.push(capture());
  }finally{w.playDemo=old;w.initPlayDemo=oldInit;w.getDemoGold=oldGold;w.getDemoBornPos=oldBirth;w.stopPlayTicker();}
  // Demo initialization resets this recording flag. Carry the prefix's actual
  // mode into native recording without changing gameplay or synthesizing state.
  w.godModeKeyPressed=Number(godMode);
  const before=capture(), history=[];
  const prefix=run.steps.filter(s=>s.state.tick<forkTick);
  for(const step of prefix.slice(-historyLimit)){
    // The initial START transition does not advance the recording clock.
    // Use observed decision boundaries, not requested burst length, for history.
    const next=run.steps[run.steps.indexOf(step)+1];
    const a=step.state.tick===0?initialState:snapshots[step.state.tick], b=snapshots[next.state.tick];
    if(!a||!b)throw Error('Missing prefix history boundary');
    history.push({candidateId:step.decision.selectedId,...step.action,
      tick:a.tick,state:a.gameStateName,afterTick:b.tick,afterState:b.gameStateName,
      before:_test.summarizeHistorySnapshot(a),after:_test.summarizeHistorySnapshot(b)});
  }
  // Seed a full recording with only events actually consumed in the prefix.
  w.playRecord=demo.action.filter((_,i)=>demo.action[i-i%2]<forkTick);
  w.goldRecord=demo.goldDrop.slice(0,w.demoGoldIdx);
  w.bornRecord=[];
  const stride=demo.bornPos[0]===2?2:1;
  for(let i=1;i<=w.demoBornIdx;i+=stride)w.bornRecord.push({x:demo.bornPos[i],y:stride===2?demo.bornPos[i+1]:1});
  w.recordCount=forkTick;w.goldRecordIdx=0;w.bornRecordIdx=0;
  w.playRecordTime=forkTick;w.recordState=0;
  w.lastKeyCode=w.playRecord.at(-1);w.recordKeyCode=w.lastKeyCode;w.keyPressed=0;w.alwaysRecord=0;
  w.curDemoData={ai:w.AI_VERSION,time:0};
  w.playMode=w.PLAY_MODERN;w.recordMode=w.RECORD_KEY;
  const after=JSON.parse(JSON.stringify(hooks.snapshot()));
  if(JSON.stringify({...before,playMode:after.playMode,tick:after.tick,timing:after.timing})!==JSON.stringify(after))
    throw Error('Handoff changed gameplay snapshot');
  w.__targetedContinuation={history,prefixDecisions:prefix.length};
  return {initialState,before,after,history,prefixStates:prefix.filter(s=>s.state.tick>0).map(s=>snapshots[s.state.tick]),
    prefixDecisions:prefix.length,nativeMode:w.playMode===w.PLAY_MODERN,
    recordingPrefix:{actions:w.playRecord.length,gold:w.goldRecord.length,births:w.bornRecord.length}};
}

export function finalizeInBrowser() {
  const hooks = window.lodeRunnerAgentHooks;
  const snapshot = hooks.getTerminalSnapshot() ?? hooks.snapshot();
  const success = snapshot.gameStateName === "finish";
  const reason = success ? "finished" : snapshot.gameStateName === "runner_dead" ? "runner dead" : "continuation limit";
  // Natural terminals are already dumped by hooks.step; never convert births twice.
  const recorded = hooks.getRecordedDemo();
  const demo = recorded?.level === 1 && recorded.time > 0 ? recorded : hooks.dumpFailure(reason);
  hooks.stop({ resumeTicker: false });
  return { snapshot, demo, result: success ? "success" : "failure", reason };
}
