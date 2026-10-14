import assert from 'node:assert/strict';
import test from 'node:test';
import {replayStateAt,verifyEngineContext} from './hybrid-runtime.mjs';

test('god-mode continuation fails closed on mode or context drift',()=>{
  const state={playData:1,level:1,godMode:true};
  verifyEngineContext(state,true);
  assert.throws(()=>verifyEngineContext({...state,godMode:false},true));
  assert.throws(()=>verifyEngineContext({...state,godMode:undefined},true));
  assert.throws(()=>verifyEngineContext({...state,level:2},true));
  assert.throws(()=>verifyEngineContext({...state,playData:2},true));
});

test('natural terminal sharing a tick does not replace a decision boundary',()=>{
  const initialState={tick:0,gameStateName:'start',godMode:true};
  const running={tick:8,gameStateName:'running',godMode:true};
  const terminal={tick:8,gameStateName:'finish',godMode:true};
  const replay={initialState,states:[running],terminal};
  assert.equal(replayStateAt(replay,0),initialState);
  assert.equal(replayStateAt(replay,8),running);
  assert.equal(replayStateAt(replay,8,true),terminal);
  assert.throws(()=>replayStateAt(replay,9));
});

test('limited continuation can end at a running replay boundary',()=>{
  const state={tick:8,gameStateName:'running',godMode:true};
  const replay={states:[state],terminal:{tick:10,gameStateName:'running',godMode:true}};
  assert.equal(replayStateAt(replay,8,true),state);
});
