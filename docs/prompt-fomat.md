# Improve Agent Prompt State Formatting for Classic Level 1

## Summary
Refactor the prompt input so the LLM sees a clean layered board model: structural terrain grid, separate actor coordinates, explicit gold state, and compact timing/movement summaries. Do not include the active/live grid in the LLM prompt.

## Key Decisions
- State that Classic level 1 uses a fixed `28 x 16` ASCII coordinate system with `(0,0)` at top-left.
- Use `terrainGrid` as the only full grid shown to the LLM.
- Remove gold, guards, and runner from `terrainGrid`; represent them in separate lists.
- Do not include `activeGrid` in the prompt. It may remain in raw snapshots for backend/debug compatibility, but it is not prompt context.
- Use `(x,y)` coordinates as the authoritative live position format for runner and guards.
- Keep offsets only as summarized movement state, not raw primary context.
- Summarize all gold as one list: visible positions plus guards carrying gold.
- Present timing as a short decision aid: current tick, elapsed time, 16-tick second phase, and recent behavior summary.

## Implementation Changes
- Update `public/game/lodeRunner.agentHooks.js` snapshot output additively:
  - `dimensions: { width: 28, height: 16 }`
  - `terrainGrid`: structural movement grid with gold, guards, and runner removed/replaced by empty cells
  - `gold: { remainingCount, complete, visiblePositions, carriedByGuards }`
  - `timing: { recordTick, gameTime, playTickTimer, ticksPerSecond: 16, secondPhase }`
  - compact runner/guard summaries for centered state, offset direction, and same-row relationships
- Keep legacy `grid` / `baseGrid` fields if needed for compatibility, but stop using them as primary prompt sections.
- Update `agent/prompt.py`:
  - add a “Board Format” guide
  - render only `terrainGrid` as the full board
  - render runner, guards, and gold as compact coordinate lists
  - render timing as a short block
  - keep compressed recent behavior
  - remove wording about “live actor grid”
- Update `agent/reasoning_tools.py`:
  - prefer `terrainGrid` for structural scans
  - prefer `gold.visiblePositions` for gold targets
  - fall back to old `baseGrid` only for compatibility
- Update `public/AGENT_RULES.md`:
  - explain that terrain, actors, and gold are separate layers
  - say gold is dynamic objective state, not permanent terrain

## Test Plan
- Run `.venv/bin/python -m py_compile agent/*.py`.
- Run `node --check public/game/lodeRunner.agentHooks.js`.
- Run `npm run build`.
- Add a prompt-format smoke check confirming:
  - prompt includes `28 x 16`
  - prompt includes `terrainGrid`
  - prompt includes runner coordinates
  - prompt includes guard coordinates
  - prompt includes gold positions
  - prompt includes timing
  - prompt does not include `activeGrid` / live actor grid
- Browser smoke check:
  - start Classic level 1 agent mode
  - inspect one trace step or backend prompt output for clear layer separation
  - confirm stepping, traces, and recording save still work

## Example Prompt Input:

* You are choosing the next short Lode Runner input burst for Classic level 1.
* Return exactly one next action burst. Choose one allowed keycode and a tick count from 1 to 20.
* Allowed keycodes: stop=32, left=37, right=39, up=38, down=40, dig_left=90, dig_right=88.
* Return this JSON shape: {"keyCode": 39, "ticks": 4, "reason": "brief explanation"}.

### Current live snapshot:
Board format:
- Classic level 1 is a fixed 28 x 16 ASCII grid.
- Coordinates use (x,y), with (0,0) at the top-left.
- `terrainGrid` is structural terrain only. It does not contain gold, runner, or guards.
- In terrainGrid rows, `.` means empty space. Other symbols are structural tiles at the x-column shown above.
- Runner, guards, and gold are listed separately as coordinates.
- Read terrain in physical movement terms: ladders support vertical climb up/down; ropes support horizontal crossing while open air and falling may exist below them.
- The ladder and rope coordinate lists are authoritative validation aids. If your visual read of the 2D grid disagrees with those lists, trust the coordinate lists.
- If the runner is standing on an `H` ladder coordinate, horizontal movement is no longer ladder progress; choose `up` or `down` to change row.
- Do not choose `up` unless movement affordance says `canMoveUp=yes`; a nearby ladder is not enough.
- Moving toward a same-row guard is not creating space. Under high or critical guard pressure, move away, climb if valid now, or dig a legal trap.
- Offsets are in-tile movement: (0,0) means centered; nonzero offsets matter near guards, gold, ladders, ropes, and falls.

Terrain tile legend:
- `.` = empty space
- `#` = diggable brick
- `@` = solid indestructible block
- `H` = ladder
- `-` = rope / bar
- `X` = trap / dug hole
- `?` = unknown / missing cell

Game state:
- playData=1 level=1 playMode=2 gameState=start
- lastFailureReason=""

Timing:
- recordTick=0 gameTime=0 playTickTimer=0
- ticksPerSecond=16 secondPhase=0/16

Runner:
- position=(14,14) action=unknown offset=(0,0) centered=yes offsetDirection=centered lastLeftRight=ACT_RIGHT

Guards:
- id=0 position=(5,6) sameRowAsRunner=no action=stop hasGold=0 offset=(0,0) centered=yes offsetDirection=centered
- id=1 position=(23,6) sameRowAsRunner=no action=stop hasGold=0 offset=(0,0) centered=yes offsetDirection=centered
- id=2 position=(14,9) sameRowAsRunner=no action=stop hasGold=0 offset=(0,0) centered=yes offsetDirection=centered

Gold:
- remainingCount=6 complete=False
- visiblePositions=(4,1), (23,3), (22,6), (7,12), (24,12), (17,14)
- carriedByGuards=none

terrainGrid (structural tiles only, dot = empty):
```
      x:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27
y= 0 | . . . . . . . . . . . . . . . . . . . . . . . . . . . .
y= 1 | . . . . . . . . . . . . . . . . . . . . . . . . . . . .
y= 2 | # # # # # # # H # # # # # # # . . . . . . . . . . . . .
y= 3 | . . . . . . . H - - - - - - - - - - . . . . . . . . . .
y= 4 | . . . . . . . H . . . . # # H . . . # # # # # # # H # #
y= 5 | . . . . . . . H . . . . # # H . . . . . . . . . . H . .
y= 6 | . . . . . . . H . . . . # # H . . . . . . . . . . H . .
y= 7 | # # H # # # # # . . . . # # # # # # # # H # # # # # # #
y= 8 | . . H . . . . . . . . . . . . . . . . . H . . . . . . .
y= 9 | . . H . . . . . . . . . . . . . . . . . H . . . . . . .
y=10 | # # # # # # # # # H # # # # # # # # # # H . . . . . . .
y=11 | . . . . . . . . . H . . . . . . . . . . H . . . . . . .
y=12 | . . . . . . . . . H - - - - - - - - - - H . . . . . . .
y=13 | . . . . H # # # # # # . . . . . . . . . # # # # # # # H
y=14 | . . . . H . . . . . . . . . . . . . . . . . . . . . . H
y=15 | # # # # # # # # # # # # # # # # # # # # # # # # # # # #
```

Use coordinate lists below to validate any coordinates you read from the 2D terrainGrid before planning movement:

terrainGrid validation: ladders=(7,2), (7,3), (7,4), (14,4), (25,4), (7,5), (14,5), (25,5), (7,6), (14,6), (25,6), (2,7), (20,7), (2,8), (20,8), (2,9), (20,9), (9,10), (20,10), (9,11), (20,11), (9,12), (20,12), (4,13), (27,13), (4,14), (27,14). Use these as the authoritative climbable vertical coordinates for moving up or down.

terrainGrid validation: ropes=(8,3), (9,3), (10,3), (11,3), (12,3), (13,3), (14,3), (15,3), (16,3), (17,3), (10,12), (11,12), (12,12), (13,12), (14,12), (15,12), (16,12), (17,12), (18,12), (19,12). Use these as the authoritative horizontal crossing coordinates. Free falling may be possible from rope positions if there is no support below.

terrainGrid validation: digging
- Only `#` is diggable brick. `@` is solid indestructible terrain and is never a dig target.
- Legacy ok2Dig requires an empty side cell and a `#` target cell down-left or down-right from the runner.
- dig_left: side (13,14)=., target (13,15)=#, possible=yes
- dig_right: side (15,14)=., target (15,15)=#, possible=yes

Recent behavior:
- none

## Assumptions
- Existing raw snapshot fields can remain for compatibility, but the LLM prompt must ignore active/live grids.
- No gameplay behavior changes are intended.
- `public/AGENT_RULES.md` owns strategy language; `agent/prompt.py` owns formatting and runtime state presentation.
