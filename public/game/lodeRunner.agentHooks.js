(function () {
	"use strict";

	var AGENT_PLAY_DATA = 1;
	var AGENT_LEVEL = 1;
	var MAX_STEP_TICKS = 20;
	var manualTime = 0;
	var active = false;
	var savedState = null;
	var lastFailureReason = "";

	function isSupportedContext(playData, level) {
		return Number(playData) === AGENT_PLAY_DATA && Number(level) === AGENT_LEVEL;
	}

	function startLevel(playDataValue, levelValue) {
		if (!isSupportedContext(playDataValue, levelValue)) {
			throw new Error("Only Classic level 1 is supported");
		}
		saveState();
		active = true;
		lastFailureReason = "";
		manualTime = 0;
		playerName = playerName && playerName.length > 1 ? playerName : "Agent";
		playMode = PLAY_MODERN;
		playData = AGENT_PLAY_DATA;
		curLevel = AGENT_LEVEL;
		levelData = getPlayVerData(AGENT_PLAY_DATA);
		recordMode = RECORD_KEY;
		curDemoData = { ai: AI_VERSION, time: 0 };
		startGame(1);
		stopPlayTicker();
		disableAutoDemoTimer();
		return snapshot();
	}

	function step(keyCode, ticks) {
		if (!active) {
			throw new Error("Agent mode is not active");
		}
		var normalizedTicks = Math.max(1, Math.min(MAX_STEP_TICKS, Number(ticks) | 0));
		applyKeyCode(Number(keyCode));
		for (var i = 0; i < normalizedTicks; i++) {
			tickOnce();
			if (gameState == GAME_FINISH || gameState == GAME_RUNNER_DEAD) {
				tickOnce();
				break;
			}
			if (gameState == GAME_WAITING || gameState == GAME_OVER || gameState == GAME_WIN) {
				break;
			}
		}
		return snapshot();
	}

	function applyKeyCode(keyCode) {
		if (keyCode == KEYCODE_SPACE) {
			keyAction = ACT_STOP;
			if (recordMode) saveKeyCode(KEYCODE_SPACE, ACT_STOP);
			return;
		}
		pressKey(keyCode);
	}

	function tickOnce() {
		manualTime += 1000 / speedMode[speed];
		mainTick({ delta: 1000 / speedMode[speed], time: manualTime });
	}

	function snapshot() {
		var runnerSnapshot = snapshotRunner();
		var guardSnapshots = snapshotGuards(runnerSnapshot);
		return {
			active: active,
			supported: isSupportedContext(playData, curLevel),
			dimensions: { width: NO_OF_TILES_X, height: NO_OF_TILES_Y },
			playData: playData,
			level: curLevel,
			playMode: playMode,
			gameState: gameState,
			gameStateName: gameStateName(gameState),
			tick: recordCount || 0,
			playTickTimer: playTickTimer || 0,
			time: curTime || 0,
			timing: snapshotTiming(),
			goldCount: goldCount || 0,
			goldComplete: !!goldComplete,
			gold: snapshotGold(guardSnapshots),
			lastFailureReason: lastFailureReason,
			runner: runnerSnapshot,
			guards: guardSnapshots,
			terrainGrid: snapshotTerrainGrid(),
			grid: snapshotGrid(1),
			baseGrid: snapshotGrid(0)
		};
	}

	function snapshotRunner() {
		if (!runner || !runner.pos) return null;
		return {
			x: runner.pos.x,
			y: runner.pos.y,
			xOffset: runner.pos.xOffset,
			yOffset: runner.pos.yOffset,
			action: runner.action,
			actionName: actionName(runner.action),
			lastLeftRight: runner.lastLeftRight,
			summary: summarizePosition(runner.pos)
		};
	}

	function snapshotGuards(runnerSnapshot) {
		var result = [];
		for (var i = 0; i < guardCount; i++) {
			if (!guard[i] || !guard[i].pos) continue;
			result.push({
				id: i,
				x: guard[i].pos.x,
				y: guard[i].pos.y,
				xOffset: guard[i].pos.xOffset,
				yOffset: guard[i].pos.yOffset,
				action: guard[i].action,
				actionName: actionName(guard[i].action),
				hasGold: guard[i].hasGold || 0,
				sameRowAsRunner: !!(runnerSnapshot && guard[i].pos.y == runnerSnapshot.y),
				summary: summarizePosition(guard[i].pos)
			});
		}
		return result;
	}

	function snapshotTiming() {
		return {
			recordTick: recordCount || 0,
			gameTime: curTime || 0,
			playTickTimer: playTickTimer || 0,
			ticksPerSecond: TICK_COUNT_PER_TIME,
			secondPhase: (playTickTimer || 0) + "/" + TICK_COUNT_PER_TIME
		};
	}

	function snapshotGold(guardSnapshots) {
		var visiblePositions = [];
		if (map) {
			for (var y = 0; y < NO_OF_TILES_Y; y++) {
				for (var x = 0; x < NO_OF_TILES_X; x++) {
					var cell = map[x] && map[x][y];
					if (cell && cell.base == GOLD_T) {
						visiblePositions.push({ x: x, y: y });
					}
				}
			}
		}
		return {
			remainingCount: goldCount || 0,
			complete: !!goldComplete,
			visiblePositions: visiblePositions,
			carriedByGuards: guardSnapshots.filter(function (item) {
				return item.hasGold > 0;
			}).map(function (item) {
				return { id: item.id, x: item.x, y: item.y, hasGold: item.hasGold };
			})
		};
	}

	function snapshotTerrainGrid() {
		var rows = [];
		if (!map) return rows;
		for (var y = 0; y < NO_OF_TILES_Y; y++) {
			var row = "";
			for (var x = 0; x < NO_OF_TILES_X; x++) {
				var cell = map[x] && map[x][y];
				row += cell ? terrainChar(cell.base) : "?";
			}
			rows.push(row);
		}
		return rows;
	}

	function snapshotGrid(includeActors) {
		var rows = [];
		if (!map) return rows;
		for (var y = 0; y < NO_OF_TILES_Y; y++) {
			var row = "";
			for (var x = 0; x < NO_OF_TILES_X; x++) {
				var cell = map[x] && map[x][y];
				if (!cell) {
					row += "?";
					continue;
				}
				row += tileChar(includeActors ? cell.act : cell.base);
			}
			rows.push(row);
		}
		return rows;
	}

	function summarizePosition(pos) {
		var xOffset = pos.xOffset || 0;
		var yOffset = pos.yOffset || 0;
		return {
			centered: xOffset === 0 && yOffset === 0,
			offsetDirection: offsetDirection(xOffset, yOffset)
		};
	}

	function offsetDirection(xOffset, yOffset) {
		var parts = [];
		if (xOffset < 0) parts.push("left");
		else if (xOffset > 0) parts.push("right");
		if (yOffset < 0) parts.push("up");
		else if (yOffset > 0) parts.push("down");
		return parts.length ? parts.join("/") : "centered";
	}

	function terrainChar(tile) {
		switch (tile) {
		case EMPTY_T: return " ";
		case BLOCK_T: return "#";
		case SOLID_T: return "@";
		case LADDR_T: return "H";
		case BAR_T: return "-";
		case TRAP_T: return "X";
		case HLADR_T: return goldComplete ? "H" : " ";
		case GOLD_T:
		case GUARD_T:
		case RUNNER_T:
			return " ";
		default: return "?";
		}
	}

	function tileChar(tile) {
		switch (tile) {
		case EMPTY_T: return " ";
		case BLOCK_T: return "#";
		case SOLID_T: return "@";
		case LADDR_T: return "H";
		case BAR_T: return "-";
		case TRAP_T: return "X";
		case HLADR_T: return "S";
		case GOLD_T: return "$";
		case GUARD_T: return "0";
		case RUNNER_T: return "&";
		default: return "?";
		}
	}

	function actionName(action) {
		switch (action) {
		case ACT_STOP: return "stop";
		case ACT_LEFT: return "left";
		case ACT_RIGHT: return "right";
		case ACT_UP: return "up";
		case ACT_DOWN: return "down";
		case ACT_FALL: return "fall";
		case ACT_FALL_BAR: return "fall_bar";
		case ACT_DIG_LEFT: return "dig_left";
		case ACT_DIG_RIGHT: return "dig_right";
		case ACT_DIGGING: return "digging";
		case ACT_IN_HOLE: return "in_hole";
		case ACT_CLIMB_OUT: return "climb_out";
		case ACT_REBORN: return "reborn";
		default: return "unknown";
		}
	}

	function gameStateName(state) {
		switch (state) {
		case GAME_START: return "start";
		case GAME_RUNNING: return "running";
		case GAME_FINISH: return "finish";
		case GAME_FINISH_SCORE_COUNT: return "finish_score_count";
		case GAME_WAITING: return "waiting";
		case GAME_PAUSE: return "pause";
		case GAME_NEW_LEVEL: return "new_level";
		case GAME_RUNNER_DEAD: return "runner_dead";
		case GAME_OVER_ANIMATION: return "game_over_animation";
		case GAME_OVER: return "game_over";
		case GAME_NEXT_LEVEL: return "next_level";
		case GAME_PREV_LEVEL: return "prev_level";
		case GAME_LOADING: return "loading";
		case GAME_WIN_SCORE_COUNT: return "win_score_count";
		case GAME_WIN: return "win";
		default: return "unknown";
		}
	}

	function getRecordedDemo() {
		return curDemoData;
	}

	function dumpFailure(reason) {
		lastFailureReason = String(reason || "agent failed");
		if (recordMode == RECORD_KEY) {
			recordModeDump(GAME_RUNNER_DEAD);
		}
		if (curDemoData) {
			curDemoData.state = 0;
		}
		return curDemoData;
	}

	function stop(options) {
		options = options || {};
		active = false;
		stopPlayTicker();
		keyAction = ACT_STOP;
		if (options.resumeTicker) {
			startPlayTicker();
		}
		if (savedState && options.restoreState) {
			playMode = savedState.playMode;
			playData = savedState.playData;
			curLevel = savedState.curLevel;
			levelData = savedState.levelData;
			recordMode = savedState.recordMode;
			savedState = null;
		}
		return snapshot();
	}

	function saveState() {
		savedState = {
			playMode: playMode,
			playData: playData,
			curLevel: curLevel,
			levelData: levelData,
			recordMode: recordMode
		};
	}

	window.lodeRunnerAgentHooks = {
		startLevel: startLevel,
		step: step,
		snapshot: snapshot,
		stop: stop,
		getRecordedDemo: getRecordedDemo,
		dumpFailure: dumpFailure,
		isSupportedContext: isSupportedContext
	};
})();
