Local n8n + Excel (four files) setup
Note: This version uses only n8n nodes (no Code node, no Python).

Files created
- data/config.xlsx (not used in manual mode)
- data/prices.xlsx
- data/state.xlsx
- data/signals.xlsx

Workflow A: Collector (local Excel, manual input)
1) Manual Trigger

2) Set manual config
   - symbol: edit to the ticker you want (example: AAPL.US)
   - interval: d
   - active: true

3) Read Binary File (state.xlsx) -> Spreadsheet File (state)
   - Operation: Read from file
   - Sheet Name: state

4) Merge (manual config + state by symbol)
   - Mode: Combine by Fields
   - Join: Enrich Input 1

5) Set defaults
   - last_date = 1900-01-01 when missing
   - active_flag = TRUE/FALSE
   - interval = d when missing

6) IF (active_flag = TRUE)

7) HTTP Request (Stooq CSV)
   - Method: GET
   - Response Format: File
   - Put Output in Field: data
   - URL:
     ={{ 'https://stooq.com/q/d/l/?s=' + $json.symbol + '&i=' + $json.interval }}

8) Extract From File (CSV)
   - Operation: Extract From CSV
   - Input Binary Field: data

9) IF (Date exists)

10) IF (Date > last_date)

11) Set (Map fields + key)
   - key = symbol|date
   - symbol/date/open/high/low/close/volume

12) Read Binary File (prices.xlsx) -> Spreadsheet File (prices)

13) Merge (Wait for prices + new rows)
   - Mode: Choose Branch (Wait for All Inputs)
   - Output: empty item (sync barrier)

14) Set combined prices (rows = existing + new)

15) Item Lists: Split Out Items (rows)

16) Set (Normalize price row: key/symbol/date)
   - trims whitespace
   - accepts header variants (Symbol/Date/KEY or extra spaces)
   - works if rows are nested under `rows` after split

17) Item Lists: Remove Duplicates (by key)

18) Item Lists: Sort (symbol, date)

19) Spreadsheet File (Write prices) -> Write Binary File (prices.xlsx)

20) Item Lists: Summarize (max date by symbol)

21) Set (symbol, last_date)

22) Spreadsheet File (Write state) -> Write Binary File (state.xlsx)

Workflow B: Error Handler (local Excel)
1) Error Trigger
2) Set (log_line)
3) Convert to Binary
4) Write Binary File (append logs/error.log)

Workflow C: Analyzer (local Excel, gemini)
1) Manual Trigger
2) Set analyzer params
   - symbol: 분석할 종목 (예: AAPL.US)
   - model: gemini-1.5-flash
   - lookback: 60
3) Reads `data/prices.xlsx` and calls Gemini, then upserts 1 row per symbol into `data/signals.xlsx` (key: `symbol|gemini`)

Gemini key
- n8n 프로세스 환경변수 `GEMINI_API_KEY`가 필요함 (설정 후 n8n 재시작)

Notes
- Close Excel files before running workflows (file lock).
- Start with one symbol (AAPL.US) to verify the pipeline.
- .env 사용 시: `scripts/start_n8n_with_env.ps1` 실행하면 `.env` 내용을 환경변수로 올리고 n8n을 시작함 (PowerShell).

