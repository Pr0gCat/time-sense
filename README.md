# time-sense

讓 coding agent 有「時間觀念」的 skill + omp plugin：先估時、先取樣、設期限、盯住委派出去的工作、依自身歷史校準估計，並且懂得放棄。

## 解決的 5 個問題

1. 不先優化就直接跑耗時數小時的 action。
2. 派出 subagent / 背景 task 後無限等待，沒有 watchdog。
3. 估時亂猜：高估難度、用人類工時（人日）尺度。
4. 做事中途不優化自己的流程。
5. 不懂放棄：同一做法一直重試、被沉沒成本綁住。

## 對應機制

| 問題 | 常駐規則（`rules/time-sense.md`） | Reference | tb 指令 |
|---|---|---|---|
| 1. 不先優化 | Preflight：>2 min 或未知先取樣外推 | `references/preflight.md` | `tb wrap --est <d> -- <sample cmd>` |
| 2. 無限等待 | Watchdog：每個委派都有預算、計時、每次喚醒 `tb check` | `references/watchdog.md` | `tb start ... --kind subagent`、`tb check` |
| 3. 估時亂猜 | 用 agent 時間（tool call × ~20s + 量測機器時間），不用人日 | `references/estimation.md` | `tb est <d> --kind <k>`、`tb calib` |
| 4. 不優化流程 | 每階段 checkpoint：重複 3 次就寫腳本、獨立呼叫平行化 | `references/process-optimization.md` | `tb start <phase> --kind step` |
| 5. 不懂放棄 | 硬期限或同做法失敗 3 次無新資訊 → 停 | `references/quitting.md` | `tb stop <id> --outcome abandoned` |

預設門檻：preflight >2 min；先優化 >10 min（優化花費 ≤ 預估 10%）；軟期限 1.5×、硬期限 3× 校準估計；同做法失敗 3 次停。數值同時存在於 `SKILL.md` 門檻表、`rules/time-sense.md`、`tb.py` 常數三處，修改時三處一起改。

## 目錄結構

```
time-sense/
  package.json                 # omp plugin manifest
  index.cjs                    # omp extension：把常駐規則注入 system prompt
  install.py                   # Claude Code / Codex 安裝器（複製檔案，不用 symlink）
  INSTALL.md                   # 給 AI agent 的安裝說明
  rules/time-sense.md          # 常駐規則唯一來源（{{TB}} = tb.py 絕對路徑）
  skills/time-sense/
    SKILL.md                   # 主 skill：核心迴圈、門檻表、tb 速查
    references/*.md            # 5 份 playbook，對應 5 個問題
    scripts/tb.py              # 時間預算 CLI（Python ≥3.9，只用標準庫）
    scripts/claude_hook.py     # Claude Code hook：強制執行規則
  tests/                       # unittest：test_tb.py、test_claude_hook.py
```

## AI 安裝

把下面這句貼給你的 coding agent（omp、Claude Code 或 Codex）：

```
Install time-sense by following https://github.com/Pr0gCat/time-sense/blob/main/INSTALL.md
```

Agent 會依 `INSTALL.md` 安裝到它所在的環境、跑驗證，並提醒你開新 session。

## 手動安裝

### omp（Oh My Pi）

```bash
omp plugin install github:Pr0gCat/time-sense
omp plugin list      # 應顯示 time-sense
```

`index.cjs` 在每次 `before_agent_start` 把規則（`{{TB}}` 已換成實際路徑）追加到 system prompt；`skills/time-sense/` 會被 omp 自動發現為 skill。更新：`omp plugin upgrade time-sense`；移除：`omp plugin uninstall time-sense`。

### Claude Code

```bash
git clone https://github.com/Pr0gCat/time-sense && python3 time-sense/install.py claude
```

安裝器會複製 skill 到 `~/.claude/skills/time-sense/`、把規則寫進 `~/.claude/CLAUDE.md`（以 `<!-- time-sense:begin/end -->` 標記）、把 hook 合併進 `~/.claude/settings.json`（保留既有 hooks），首次修改前各備份一份 `*.bak-time-sense`。重跑即更新；`--uninstall` 只移除 time-sense 的部分。

實測 Claude Code 對 MUST 規則的遵守時有時無（會略過 `tb wrap`、前景派 subagent、重跑慢指令），所以附 hook 強制執行：

| 情況 | Hook 行為 |
|---|---|
| Bash 設了 >60s 的 timeout，卻沒用 `tb wrap` | 拒絕，要求用 `tb wrap --est <自己的估計>` 重送（背景執行的指令除外） |
| 上一個呼叫跑了 ≥30s，下一個呼叫又跑同一個昂貴指令，中間沒有任何修改 | 拒絕，要求重用結果；確實需要重跑時在指令後加 `# time-sense: rerun` |
| Bash 沒用 `tb wrap` 卻跑了 ≥30s | 在 Claude 的 context 補一則提醒 |
| 前景派 subagent，或沒有 10 分鐘內啟動的 `--kind subagent` 計時器 | 拒絕 |
| Subagent 內 `tb wrap` 的硬期限（3× 校準估計）超過 subagent 剩餘預算 | 拒絕，告知可用的最大 `--est` |

Hook 的 session 狀態存在 `$TIME_SENSE_HOME/claude-sessions/`。

### Codex

```bash
git clone https://github.com/Pr0gCat/time-sense && python3 time-sense/install.py codex
```

複製 skill 到 `~/.codex/skills/time-sense/`、規則寫進 `~/.codex/AGENTS.md`，不含 hook。

> unverified — 需確認 Codex skills 路徑（`~/.codex/skills/` 為假設）。

## tb.py 用法

```bash
TB="python3 ~/.claude/skills/time-sense/scripts/tb.py"   # 或 repo 內的 skills/time-sense/scripts/tb.py

$TB est 5m --kind action
# tb: est 5m00s x0.62 (n=7 action) -> 3m06s; soft 4m39s; hard 9m18s

$TB start sub-auth --est 8m --kind subagent --note "auth refactor"
$TB check            # exit 0 = OK，10 = SOFT，20 = HARD
$TB stop sub-auth --outcome done      # done | failed | abandoned
$TB calib            # 各 kind 的樣本數、actual/est 中位數、校準係數

$TB wrap --est 3m -- npm test
# 超過軟期限印 SOFT 警告；到硬期限殺掉整個程序樹，exit 124，記為 abandoned
# 加 --no-kill 則只警告不殺
```

- 時長格式：純秒數（`90`）或 `1h30m`、`5m`、`90s`。
- Kind：`action`（指令/build/test）、`subagent`（委派 agent 或背景 task）、`step`（自己工作的一個階段）、`task`（整個使用者請求）。
- 校準：取該 kind 最近 20 筆 `done`/`failed` 紀錄的 actual/est 中位數，夾在 `[0.25, 4.0]`；不足 3 筆時係數為 1.00（`uncalibrated`）。`abandoned` 不計入（實際時間被截斷）。
- 一定要用真實 outcome `tb stop`，校準才誠實。

## 資料位置

- 狀態目錄：環境變數 `TIME_SENSE_HOME`，預設 `~/.time-sense`。
  - `ledger.jsonl`：已結束計時器的只追加紀錄。
  - `active.json`：進行中的計時器。
- 資料只存在本機，不會上傳。
- 超過 24 小時的進行中計時器會在下次 `tb check` 時被丟棄（不寫入 ledger）。

## 測試

```bash
python3 -m unittest discover -s tests -v
```
