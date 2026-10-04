// Executed only in the extractor's isolated legacy page; no production wrapper.
export async function replayInPage({ demo, maxTicks, capture }) {
  const w = window;
  w.clearIdleDemoTimer();
  w.disableAutoDemoTimer();
  w.disableStageClickEvent();
  w.stopPlayTicker();
  w.playData = 1;
  w.curLevel = demo.level;
  w.levelData = w.getPlayVerData(1);
  w.playerDemoData = [];
  w.playerDemoData[demo.level - 1] = demo;
  w.playMode = w.PLAY_DEMO_ONCE;
  w.recordMode = 0;
  const original = w.mainTick;
  const states = [], checkpoints = [];
  const changes = new Set(demo.action.filter((_, i) => i % 2 === 0));
  let lastSample = -maxTicks, calls = 0;
  const started = performance.now();
  const read = () => {
    const s = w.lodeRunnerAgentHooks.snapshot();
    s.legacyRecordTick = s.tick;
    s.tick = w.demoTickCount;
    s.timing.recordTick = s.tick;
    return JSON.parse(JSON.stringify(s));
  };
  const checkpoint = s => ({tick: s.tick, state: s.gameStateName, runner: s.runner,
    guards: s.guards, gold: s.gold, grid: s.grid, terrainGrid: s.terrainGrid,
    activeDig: s.activeDig, openHoles: s.openHoles});
  return new Promise((resolve, reject) => {
    const finish = (error, terminal) => {
      clearTimeout(timer);
      w.stopPlayTicker();
      w.mainTick = original;
      if (error) return reject(error);
      if (capture) {
        if (states.at(-1)?.tick === terminal.tick) states[states.length - 1] = terminal;
        else states.push(terminal);
      }
      checkpoints.push(checkpoint(terminal));
      resolve({states, checkpoints, terminal, calls, demoSpeed: w.demoSpeed,
        aiVersion: w.curAiVersion,
        elapsedMs: performance.now() - started, goldCursor: w.demoGoldIdx,
        bornCursor: w.demoBornIdx});
    };
    const timer = setTimeout(() => finish(new Error("Replay wall-time watchdog expired")),
      Math.max(60000, (demo.time + 200) / w.demoSpeed * 1000 * 3));
    w.mainTick = event => {
      try {
        if (w.gameState !== w.GAME_RUNNING) throw new Error("Unexpected replay state " + w.gameState);
        const tick = w.demoTickCount;
        if (changes.has(tick) || tick - lastSample >= maxTicks) {
          const s = read();
          if (capture) states.push(s);
          checkpoints.push(checkpoint(s));
          lastSample = tick;
        }
        original(event);
        calls++;
        if (w.gameState === w.GAME_FINISH || w.gameState === w.GAME_RUNNER_DEAD) {
          finish(null, read());
        } else if (w.demoTickCount > demo.time + 2) {
          finish(null, read()); // replay integrity failure, retained for diagnosis
        }
      } catch (error) { finish(error); }
    };
    try { w.startGame(1); } catch (error) { finish(error); }
  });
}
