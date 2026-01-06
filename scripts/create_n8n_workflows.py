import json
import urllib.request
from pathlib import Path


API_BASE = "http://localhost:5678/api/v1"
WORKFLOW_A_NAME = "Collector (local excel)"
WORKFLOW_B_NAME = "Error Handler (local excel)"
WORKFLOW_C_NAME = "Analyzer (local excel, gemini)"
BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = str((BASE_DIR / "data" / "config.xlsx").resolve())
PRICES_PATH = str((BASE_DIR / "data" / "prices.xlsx").resolve())
STATE_PATH = str((BASE_DIR / "data" / "state.xlsx").resolve())
SIGNALS_PATH = str((BASE_DIR / "data" / "signals.xlsx").resolve())
LOG_PATH = str((BASE_DIR / "logs" / "error.log").resolve())


def load_api_key():
    key = None
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("N8N_API_KEY="):
            key = line.split("=", 1)[1]
            break
    if not key:
        raise RuntimeError("N8N_API_KEY not found in .env")
    return key


def api_request(method, path, api_key, payload=None):
    url = f"{API_BASE}{path}"
    data = None
    headers = {"X-N8N-API-KEY": api_key}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} {e.reason} for {method} {path}: {detail}") from e


def list_workflows(api_key):
    resp = api_request("GET", "/workflows", api_key)
    return resp.get("data", [])


def upsert_workflow(api_key, name, workflow, activate=False):
    existing = next((w for w in list_workflows(api_key) if w.get("name") == name), None)
    if existing:
        workflow["name"] = name
        updated = api_request("PUT", f"/workflows/{existing['id']}", api_key, workflow)
        if activate:
            activate_workflow(api_key, updated["id"])
        return updated
    created = api_request("POST", "/workflows", api_key, workflow)
    if activate:
        activate_workflow(api_key, created["id"])
    return created


def activate_workflow(api_key, workflow_id):
    api_request("POST", f"/workflows/{workflow_id}/activate", api_key, {"active": True})


def build_error_workflow():
    return {
        "name": WORKFLOW_B_NAME,
        "nodes": [
            {
                "parameters": {},
                "name": "Error Trigger",
                "type": "n8n-nodes-base.errorTrigger",
                "typeVersion": 1,
                "position": [240, 300],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "log_line",
                                "value": "={{ '[' + ($json.execution && $json.execution.startedAt ? $json.execution.startedAt : '') + '] ' + ($json.workflow && $json.workflow.name ? $json.workflow.name : '') + ' ' + ($json.error && $json.error.node && $json.error.node.name ? $json.error.node.name : '') + ' ' + ($json.error && $json.error.message ? $json.error.message : '') + \"\\n\" }}",
                            }
                        ]
                    },
                },
                "name": "Set log line",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [520, 300],
            },
            {
                "parameters": {
                    "mode": "jsonToBinary",
                    "convertAllData": False,
                    "sourceKey": "log_line",
                    "destinationKey": "data",
                    "options": {
                        "encoding": "utf8",
                        "fileName": "error.log",
                        "mimeType": "text/plain",
                        "useRawData": True,
                    },
                },
                "name": "To binary",
                "type": "n8n-nodes-base.moveBinaryData",
                "typeVersion": 1,
                "position": [760, 300],
            },
            {
                "parameters": {
                    "fileName": LOG_PATH,
                    "dataPropertyName": "data",
                    "options": {
                        "append": True,
                    },
                },
                "name": "Write error log",
                "type": "n8n-nodes-base.writeBinaryFile",
                "typeVersion": 1,
                "position": [1000, 300],
            },
        ],
        "connections": {
            "Error Trigger": {
                "main": [[{"node": "Set log line", "type": "main", "index": 0}]]
            },
            "Set log line": {
                "main": [[{"node": "To binary", "type": "main", "index": 0}]]
            },
            "To binary": {
                "main": [[{"node": "Write error log", "type": "main", "index": 0}]]
            },
        },
        "settings": {"timezone": "Asia/Seoul"},
    }


def build_collector_workflow(error_workflow_id):
    return {
        "name": WORKFLOW_A_NAME,
        "nodes": [
            {
                "parameters": {},
                "name": "Manual Trigger",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [200, 300],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "query",
                                "value": "",
                            },
                            {
                                "name": "interval",
                                "value": "d",
                            },
                        ],
                        "boolean": [
                            {
                                "name": "active",
                                "value": True,
                            }
                        ],
                    },
                },
                "name": "Set manual config",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [400, 150],
            },
            {
                "parameters": {
                    "authentication": "none",
                    "requestMethod": "GET",
                    "url": "={{ 'https://query1.finance.yahoo.com/v1/finance/search?q=' + encodeURIComponent($json.query || $json.company || $json.symbol || 'AAPL') + '&quotesCount=3&newsCount=0' }}",
                    "responseFormat": "json",
                    "options": {
                        "ignoreResponseCode": True
                    },
                },
                "name": "Lookup symbol",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 2,
                "position": [620, 120],
            },
            {
                "parameters": {
                    "mode": "chooseBranch",
                    "numberInputs": 2,
                    "chooseBranchMode": "waitForAll",
                    "output": "empty",
                },
                "name": "Wait for symbol lookup",
                "type": "n8n-nodes-base.merge",
                "typeVersion": 3.2,
                "position": [840, 150],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "company",
                                "value": "={{ ($node[\"Set manual config\"].json.query || $node[\"Set manual config\"].json.company || '').toString().trim() }}",
                            },
                            {
                                "name": "symbol",
                                "value": "={{ (() => { const rawSym = ($node['Set manual config'].json.symbol || '').toString().trim(); const query = ($node['Set manual config'].json.query || '').toString().trim(); const company = ($node['Set manual config'].json.company || query).toString().trim(); const res = $node['Lookup symbol'].json || {}; const quotes = res.quotes || res.finance?.result || []; const fromQuotes = quotes.find(q => (String(q.quoteType || '').toLowerCase() === 'equity') && q.symbol) || quotes[0]; const fallbackMap = { '삼성전자': '005930.KS', '카카오': '035720.KS', '네이버': '035420.KS', '엔씨소프트': '036570.KS', '엔씨': '036570.KS', '현대차': '005380.KS', '기아': '000270.KS', 'lg에너지솔루션': '373220.KS', 'lg화학': '051910.KS', 'sk하이닉스': '000660.KS', 'posco': '005490.KS', '포스코': '005490.KS' }; const lowerQ = query.toLowerCase(); const mapHit = Object.keys(fallbackMap).find(k => lowerQ.includes(k)); if (rawSym) return rawSym.toUpperCase(); if (mapHit) return fallbackMap[mapHit]; let sym = (fromQuotes && fromQuotes.symbol ? String(fromQuotes.symbol) : (company || query)).toUpperCase(); if (!sym) return ''; if (sym.includes('.')) return sym; const exchange = (fromQuotes && fromQuotes.exchange ? String(fromQuotes.exchange) : '').toUpperCase(); const mapEx = { NMS: 'US', NYQ: 'US', NCM: 'US', NGM: 'US', NIM: 'US', ASE: 'US', BATS: 'US', PCX: 'US', NGQ: 'US', KSC: 'KS', KSE: 'KS', KOE: 'KS', KOS: 'KQ', KOSDAQ: 'KQ' }; const suffix = mapEx[exchange] || 'US'; return sym + '.' + suffix; })() }}",
                            },
                            {
                                "name": "interval",
                                "value": "={{ ($node['Set manual config'].json.interval || 'd').toString().trim() || 'd' }}",
                            },
                        ],
                        "boolean": [
                            {
                                "name": "active",
                                "value": "={{ $node['Set manual config'].json.active === true || $node['Set manual config'].json.active === 'TRUE' || $node['Set manual config'].json.active === 'true' }}",
                            }
                        ],
                    },
                },
                "name": "Set resolved config",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [1060, 150],
            },
            {
                "parameters": {
                    "filePath": STATE_PATH,
                    "dataPropertyName": "data",
                },
                "name": "Read State File",
                "type": "n8n-nodes-base.readBinaryFile",
                "typeVersion": 1,
                "position": [400, 300],
            },
            {
                "parameters": {
                    "filePath": PRICES_PATH,
                    "dataPropertyName": "data",
                },
                "name": "Read Prices File",
                "type": "n8n-nodes-base.readBinaryFile",
                "typeVersion": 1,
                "position": [400, 450],
            },
            {
                "parameters": {
                    "operation": "fromFile",
                    "binaryPropertyName": "data",
                    "fileFormat": "xlsx",
                    "options": {
                        "sheetName": "state",
                        "headerRow": True,
                    },
                },
                "name": "Read State Sheet",
                "type": "n8n-nodes-base.spreadsheetFile",
                "typeVersion": 2,
                "position": [620, 300],
            },
            {
                "parameters": {
                    "operation": "fromFile",
                    "binaryPropertyName": "data",
                    "fileFormat": "xlsx",
                    "options": {
                        "sheetName": "prices",
                        "headerRow": True,
                    },
                },
                "name": "Read Prices Sheet",
                "type": "n8n-nodes-base.spreadsheetFile",
                "typeVersion": 2,
                "position": [620, 450],
            },
            {
                "parameters": {
                    "mode": "combine",
                    "combineBy": "combineByFields",
                    "advanced": False,
                    "fieldsToMatchString": "symbol",
                    "joinMode": "enrichInput1",
                },
                "name": "Merge Config/State",
                "type": "n8n-nodes-base.merge",
                "typeVersion": 3.2,
                "position": [860, 230],
            },
            {
                "parameters": {
                    "keepOnlySet": False,
                    "values": {
                        "boolean": [
                            {
                                "name": "active_flag",
                                "value": "={{ $json.active === true || $json.active === 'TRUE' || $json.active === 'true' }}",
                            }
                        ],
                        "string": [
                            {
                                "name": "last_date",
                                "value": "={{ $json.last_date ? $json.last_date : '1900-01-01' }}",
                            },
                            {
                                "name": "interval",
                                "value": "={{ $json.interval ? $json.interval : 'd' }}",
                            },
                        ],
                    },
                },
                "name": "Set defaults",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [1080, 230],
            },
            {
                "parameters": {
                    "conditions": {
                        "boolean": [
                            {
                                "value1": "={{ $json.active_flag }}",
                                "operation": "equal",
                                "value2": True,
                            }
                        ]
                    },
                    "combineOperation": "all",
                },
                "name": "IF active",
                "type": "n8n-nodes-base.if",
                "typeVersion": 1,
                "position": [1300, 230],
            },
            {
                "parameters": {
                    "authentication": "none",
                    "requestMethod": "GET",
                    "url": "={{ 'https://stooq.com/q/d/l/?s=' + $json.symbol + '&i=' + $json.interval }}",
                    "responseFormat": "file",
                    "dataPropertyName": "data",
                },
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 2,
                "position": [1520, 230],
            },
            {
                "parameters": {
                    "operation": "csv",
                    "binaryPropertyName": "data",
                    "options": {
                        "headerRow": True,
                    },
                },
                "name": "Extract CSV",
                "type": "n8n-nodes-base.extractFromFile",
                "typeVersion": 1,
                "position": [1740, 230],
            },
            {
                "parameters": {
                    "conditions": {
                        "string": [
                            {
                                "value1": "={{ $json.Date }}",
                                "operation": "isNotEmpty",
                            }
                        ]
                    },
                    "combineOperation": "all",
                },
                "name": "IF has date",
                "type": "n8n-nodes-base.if",
                "typeVersion": 1,
                "position": [1860, 230],
            },
            {
                "parameters": {
                    "mode": "chooseBranch",
                    "numberInputs": 2,
                    "chooseBranchMode": "waitForAll",
                    "output": "empty",
                },
                "name": "Wait for price window data",
                "type": "n8n-nodes-base.merge",
                "typeVersion": 3.2,
                "position": [1080, 320],
            },
            {
                "parameters": {
                    "conditions": {
                        "number": [
                            {
                                "value1": "={{ Date.parse($json.Date || '1900-01-01') }}",
                                "operation": "larger",
                                "value2": "={{ Date.parse($items(\"Set defaults\")[0].json.last_date || '1900-01-01') }}",
                            }
                        ]
                    },
                    "combineOperation": "all",
                },
                "name": "IF new date",
                "type": "n8n-nodes-base.if",
                "typeVersion": 1,
                "position": [2060, 230],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "key",
                                "value": "={{ $items(\"Set defaults\")[0].json.symbol + '|' + $json.Date }}",
                            },
                            {
                                "name": "symbol",
                                "value": "={{ $items(\"Set defaults\")[0].json.symbol }}",
                            },
                            {
                                "name": "date",
                                "value": "={{ $json.Date }}",
                            },
                        ],
                        "number": [
                            {
                                "name": "open",
                                "value": "={{ $json.Open }}",
                            },
                            {
                                "name": "high",
                                "value": "={{ $json.High }}",
                            },
                            {
                                "name": "low",
                                "value": "={{ $json.Low }}",
                            },
                            {
                                "name": "close",
                                "value": "={{ $json.Close }}",
                            },
                            {
                                "name": "volume",
                                "value": "={{ $json.Volume }}",
                            },
                        ],
                    },
                },
                "name": "Set price row",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [2180, 230],
            },
            {
                "parameters": {
                    "mode": "chooseBranch",
                    "numberInputs": 2,
                    "chooseBranchMode": "waitForAll",
                    "output": "empty",
                },
                "name": "Wait for prices data",
                "type": "n8n-nodes-base.merge",
                "typeVersion": 3.2,
                "position": [2400, 230],
            },
            {
                "parameters": {
                    "mode": "manual",
                    "fields": {
                        "values": [
                            {
                                "name": "rows",
                                "type": "arrayValue",
                                "arrayValue": "={{ $items(\"Read Prices Sheet\").map(item => item.json).concat($items(\"Set price row\").map(item => item.json)) }}",
                            }
                        ]
                    },
                    "include": "none",
                },
                "name": "Set combined prices",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.2,
                "position": [2620, 230],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "splitOutItems",
                    "fieldToSplitOut": "rows",
                    "include": "noOtherFields",
                },
                "name": "Split combined prices",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [2840, 230],
            },
            {
                "parameters": {
                    "keepOnlySet": False,
                    "values": {
                        "string": [
                            {
                                "name": "symbol",
                                "value": "={{ (() => { const base = ($json && $json.rows && typeof $json.rows === 'object') ? $json.rows : ($json || {}); const keys = Object.keys(base); const pick = (name) => { const key = keys.find(k => k.toLowerCase().trim() === name); return key ? base[key] : undefined; }; const val = pick('symbol'); return val !== undefined && val !== null ? String(val).trim() : ''; })() }}",
                            },
                            {
                                "name": "date",
                                "value": "={{ (() => { const base = ($json && $json.rows && typeof $json.rows === 'object') ? $json.rows : ($json || {}); const keys = Object.keys(base); const pick = (name) => { const key = keys.find(k => k.toLowerCase().trim() === name); return key ? base[key] : undefined; }; const val = pick('date'); return val !== undefined && val !== null ? String(val).trim() : ''; })() }}",
                            },
                            {
                                "name": "key",
                                "value": "={{ (() => { const base = ($json && $json.rows && typeof $json.rows === 'object') ? $json.rows : ($json || {}); const keys = Object.keys(base); const pick = (name) => { const key = keys.find(k => k.toLowerCase().trim() === name); return key ? base[key] : undefined; }; const rawKey = pick('key'); if (rawKey !== undefined && rawKey !== null && String(rawKey).trim() !== '') { return String(rawKey).trim(); } const sym = pick('symbol'); const date = pick('date'); const symVal = sym !== undefined && sym !== null ? String(sym).trim() : ''; const dateVal = date !== undefined && date !== null ? String(date).trim() : ''; return symVal && dateVal ? symVal + '|' + dateVal : ''; })() }}",
                            },
                        ]
                    },
                },
                "name": "Normalize price row",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [3060, 230],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "removeDuplicates",
                    "compare": "selectedFields",
                    "fieldsToCompare": "key",
                },
                "name": "Remove duplicate prices",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [3500, 350],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "sort",
                    "type": "simple",
                    "sortFieldsUi": {
                        "sortField": [
                            {
                                "fieldName": "symbol",
                                "order": "ascending",
                            },
                            {
                                "fieldName": "date",
                                "order": "ascending",
                            },
                        ]
                    },
                },
                "name": "Sort prices",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [3720, 250],
            },
            {
                "parameters": {
                    "operation": "toFile",
                    "fileFormat": "xlsx",
                    "binaryPropertyName": "data",
                    "options": {
                        "sheetName": "prices",
                        "headerRow": True,
                        "fileName": "prices.xlsx",
                    },
                },
                "name": "Build prices file",
                "type": "n8n-nodes-base.spreadsheetFile",
                "typeVersion": 2,
                "position": [3940, 250],
            },
            {
                "parameters": {
                    "fileName": PRICES_PATH,
                    "dataPropertyName": "data",
                },
                "name": "Write prices file",
                "type": "n8n-nodes-base.writeBinaryFile",
                "typeVersion": 1,
                "position": [4160, 250],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "summarize",
                    "fieldsToSummarize": {
                        "values": [
                            {
                                "aggregation": "max",
                                "field": "date",
                            }
                        ]
                    },
                    "fieldsToSplitBy": "symbol",
                    "options": {
                        "outputFormat": "separateItems",
                    },
                },
                "name": "Summarize state",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [3720, 450],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "symbol",
                                "value": "={{ $json.symbol }}",
                            },
                            {
                                "name": "last_date",
                                "value": "={{ $json.max_date }}",
                            },
                        ]
                    },
                },
                "name": "Set state row",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [3940, 450],
            },
            {
                "parameters": {
                    "operation": "toFile",
                    "fileFormat": "xlsx",
                    "binaryPropertyName": "data",
                    "options": {
                        "sheetName": "state",
                        "headerRow": True,
                        "fileName": "state.xlsx",
                    },
                },
                "name": "Build state file",
                "type": "n8n-nodes-base.spreadsheetFile",
                "typeVersion": 2,
                "position": [4160, 450],
            },
            {
                "parameters": {
                    "fileName": STATE_PATH,
                    "dataPropertyName": "data",
                },
                "name": "Write state file",
                "type": "n8n-nodes-base.writeBinaryFile",
                "typeVersion": 1,
                "position": [4380, 450],
            },
        ],
        "connections": {
            "Manual Trigger": {
                "main": [
                    [
                        {"node": "Set manual config", "type": "main", "index": 0},
                        {"node": "Lookup symbol", "type": "main", "index": 0},
                        {"node": "Read State File", "type": "main", "index": 0},
                        {"node": "Read Prices File", "type": "main", "index": 0},
                    ]
                ]
            },
            "Set manual config": {
                "main": [[{"node": "Wait for symbol lookup", "type": "main", "index": 0}]]
            },
            "Lookup symbol": {
                "main": [[{"node": "Wait for symbol lookup", "type": "main", "index": 1}]]
            },
            "Wait for symbol lookup": {
                "main": [[{"node": "Set resolved config", "type": "main", "index": 0}]]
            },
            "Set resolved config": {
                "main": [[{"node": "Merge Config/State", "type": "main", "index": 0}]]
            },
            "Read State File": {
                "main": [[{"node": "Read State Sheet", "type": "main", "index": 0}]]
            },
            "Read Prices File": {
                "main": [[{"node": "Read Prices Sheet", "type": "main", "index": 0}]]
            },
            "Read State Sheet": {
                "main": [[{"node": "Merge Config/State", "type": "main", "index": 1}]]
            },
            "Merge Config/State": {
                "main": [[{"node": "Set defaults", "type": "main", "index": 0}]]
            },
            "Set defaults": {
                "main": [[{"node": "IF active", "type": "main", "index": 0}]]
            },
            "IF active": {
                "main": [[{"node": "HTTP Request", "type": "main", "index": 0}], []]
            },
            "HTTP Request": {
                "main": [[{"node": "Extract CSV", "type": "main", "index": 0}]]
            },
            "Extract CSV": {
                "main": [[{"node": "IF has date", "type": "main", "index": 0}]]
            },
            "IF has date": {
                "main": [[{"node": "IF new date", "type": "main", "index": 0}], []]
            },
            "IF new date": {
                "main": [[{"node": "Set price row", "type": "main", "index": 0}], []]
            },
            "Set price row": {
                "main": [[{"node": "Wait for prices data", "type": "main", "index": 0}]]
            },
            "Read Prices Sheet": {
                "main": [[{"node": "Wait for prices data", "type": "main", "index": 1}]]
            },
            "Wait for prices data": {
                "main": [[{"node": "Set combined prices", "type": "main", "index": 0}]]
            },
            "Set combined prices": {
                "main": [[{"node": "Split combined prices", "type": "main", "index": 0}]]
            },
            "Split combined prices": {
                "main": [
                    [
                        {"node": "Normalize price row", "type": "main", "index": 0},
                    ]
                ]
            },
            "Normalize price row": {
                "main": [
                    [
                        {"node": "Remove duplicate prices", "type": "main", "index": 0},
                        {"node": "Summarize state", "type": "main", "index": 0},
                    ],
                ]
            },
            "Remove duplicate prices": {
                "main": [
                    [
                        {"node": "Sort prices", "type": "main", "index": 0},
                    ]
                ]
            },
            "Sort prices": {
                "main": [[{"node": "Build prices file", "type": "main", "index": 0}]]
            },
            "Build prices file": {
                "main": [[{"node": "Write prices file", "type": "main", "index": 0}]]
            },
            "Summarize state": {
                "main": [[{"node": "Set state row", "type": "main", "index": 0}]]
            },
            "Set state row": {
                "main": [[{"node": "Build state file", "type": "main", "index": 0}]]
            },
            "Build state file": {
                "main": [[{"node": "Write state file", "type": "main", "index": 0}]]
            },
        },
        "settings": {"timezone": "Asia/Seoul", "errorWorkflow": error_workflow_id},
    }


def build_gemini_analyzer_workflow(error_workflow_id):
    return {
        "name": WORKFLOW_C_NAME,
        "nodes": [
            {
                "parameters": {},
                "name": "Manual Trigger",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [200, 300],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "query",
                                "value": "={{ $json.body?.query ?? $json.query ?? '' }}",
                            },
                            {
                                "name": "model",
                                "value": "={{ $json.body?.model ?? $json.model ?? 'models/gemini-2.5-flash' }}",
                            },
                        ],
                        "number": [
                            {
                                "name": "lookback",
                                "value": "={{ Number($json.body?.lookback ?? $json.lookback ?? 60) }}",
                            }
                        ],
                    },
                },
                "name": "Set analyzer params",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [420, 180],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "search_query",
                                "value": "={{ (() => { const q = ($json.query || '').toString().trim(); const c = ($json.company || '').toString().trim(); const s = ($json.symbol || '').toString().trim(); const pick = q || c || s; return pick || 'AAPL'; })() }}",
                            }
                        ]
                    },
                },
                "name": "Set search query (analyzer)",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [520, 120],
            },
            {
                "parameters": {
                    "httpMethod": "POST",
                    "path": "analyze",
                    "webhookId": "analyze",
                    "responseMode": "responseNode",
                    "options": {
                        "responseContentType": "application/json",
                    },
                },
                "name": "Webhook (analyze)",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [200, 120],
            },
            {
                "parameters": {
                    "authentication": "none",
                    "requestMethod": "GET",
                    "url": "={{ 'https://query1.finance.yahoo.com/v1/finance/search?q=' + encodeURIComponent($json.search_query || 'AAPL') + '&quotesCount=3&newsCount=0&lang=ko-KR&region=KR' }}",
                    "options": {
                        "headers": {
                            "User-Agent": "Mozilla/5.0",
                            "Accept-Language": "ko,en-US;q=0.7,en;q=0.5"
                        },
                        "ignoreResponseCode": True
                    },
                    "responseFormat": "json",
                },
                "name": "Lookup symbol (analyzer)",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 2,
                "position": [640, 120],
            },
            {
                "parameters": {
                    "mode": "chooseBranch",
                    "numberInputs": 2,
                    "chooseBranchMode": "waitForAll",
                    "output": "empty",
                },
                "name": "Wait for symbol (analyzer)",
                "type": "n8n-nodes-base.merge",
                "typeVersion": 3.2,
                "position": [860, 180],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {
                                "name": "company",
                                "value": "={{ ($node['Set analyzer params'].json.query || $node['Set analyzer params'].json.company || '').toString().trim() }}",
                            },
                            {
                                "name": "symbol",
                                "value": "={{ (() => { const rawSym = ($node['Set analyzer params'].json.symbol || '').toString().trim(); const query = ($node['Set analyzer params'].json.query || '').toString().trim(); const company = ($node['Set analyzer params'].json.company || query).toString().trim(); const res = $node['Lookup symbol (analyzer)'].json || {}; const quotes = res.quotes || res.finance?.result || []; const eq = quotes.find(q => (String(q.quoteType || '').toLowerCase() === 'equity') && q.symbol) || quotes[0]; const fallbackMap = { '삼성전자': '005930.KS', '카카오': '035720.KS', '네이버': '035420.KS', '엔씨소프트': '036570.KS', '엔씨': '036570.KS', '현대차': '005380.KS', '기아': '000270.KS', 'lg에너지솔루션': '373220.KS', 'lg화학': '051910.KS', 'sk하이닉스': '000660.KS', 'posco': '005490.KS', '포스코': '005490.KS' }; const lowerQ = query.toLowerCase(); const mapHit = Object.keys(fallbackMap).find(k => lowerQ.includes(k)); if (rawSym) return rawSym.toUpperCase(); if (mapHit) return fallbackMap[mapHit]; let sym = (eq && eq.symbol ? String(eq.symbol) : (company || query)).toUpperCase(); if (!sym) return ''; if (sym.includes('.')) return sym; const exchange = (eq && eq.exchange ? String(eq.exchange) : '').toUpperCase(); const mapEx = { NMS: 'US', NYQ: 'US', NCM: 'US', NGM: 'US', NIM: 'US', ASE: 'US', BATS: 'US', PCX: 'US', NGQ: 'US', KSC: 'KS', KSE: 'KS', KOE: 'KS', KOS: 'KQ', KOSDAQ: 'KQ' }; const suffix = mapEx[exchange] || 'US'; return sym + '.' + suffix; })() }}",
                            },
                            {
                                "name": "model",
                                "value": "={{ ($node['Set analyzer params'].json.model || 'models/gemini-2.5-flash').toString().trim() || 'models/gemini-2.5-flash' }}",
                            },
                        ],
                        "number": [
                            {
                                "name": "lookback",
                                "value": "={{ Number($node['Set analyzer params'].json.lookback || 60) }}",
                            }
                        ],
                    },
                },
                "name": "Set analyzer params (resolved)",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [1080, 180],
            },
            {
                "parameters": {
                    "filePath": PRICES_PATH,
                    "dataPropertyName": "data",
                },
                "name": "Read Prices File",
                "type": "n8n-nodes-base.readBinaryFile",
                "typeVersion": 1,
                "position": [420, 320],
            },
            {
                "parameters": {
                    "operation": "fromFile",
                    "binaryPropertyName": "data",
                    "fileFormat": "xlsx",
                    "options": {
                        "sheetName": "prices",
                        "headerRow": True,
                    },
                },
                "name": "Read Prices Sheet",
                "type": "n8n-nodes-base.spreadsheetFile",
                "typeVersion": 2,
                "position": [640, 320],
            },
            {
                "parameters": {
                    "mode": "chooseBranch",
                    "numberInputs": 2,
                    "chooseBranchMode": "waitForAll",
                    "output": "empty",
                },
                "name": "Wait for price window data",
                "type": "n8n-nodes-base.merge",
                "typeVersion": 3.2,
                "position": [760, 320],
            },
            {
                "parameters": {
                    "mode": "manual",
                    "fields": {
                        "values": [
                            {
                                "name": "symbol",
                                "type": "stringValue",
                                "stringValue": "={{ (() => { const resolved = ($items('Set analyzer params (resolved)')[0].json.symbol || '').toString().trim(); if (resolved) return resolved; const prices = $items('Read Prices Sheet').map(i => i.json).filter(r => (r && (r.symbol || '').toString().trim())); prices.sort((a,b) => (b.date || '').toString().localeCompare((a.date || '').toString())); return (prices[0]?.symbol || '').toString().trim(); })() }}",
                            },
                            {
                                "name": "model",
                                "type": "stringValue",
                                "stringValue": "={{ ($items('Set analyzer params (resolved)')[0].json.model || 'models/gemini-2.5-flash').toString().trim() }}",
                            },
                            {
                                "name": "lookback",
                                "type": "numberValue",
                                "numberValue": "={{ Number($items('Set analyzer params (resolved)')[0].json.lookback || 60) }}",
                            },
                            {
                                "name": "rows",
                                "type": "arrayValue",
                                "arrayValue": "={{ (() => { const resolved = ($items('Set analyzer params (resolved)')[0].json.symbol || '').toString().trim(); const lookback = Number($items('Set analyzer params (resolved)')[0].json.lookback || 60); const items = $items('Read Prices Sheet').map(i => i.json).filter(r => r && (r.date || '').toString().trim() !== '' && (r.symbol || '').toString().trim() !== ''); items.sort((a,b) => (b.date || '').toString().localeCompare((a.date || '').toString())); const autoSymbol = (items[0]?.symbol || '').toString().trim(); const symbol = resolved || autoSymbol; const rows = items.filter(r => (r.symbol || '').toString().trim() === symbol); return rows.slice(0, lookback); })() }}",
                            },
                            {
                                "name": "as_of",
                                "type": "stringValue",
                                "stringValue": "={{ (() => { const rows = $json.rows || []; return rows.length ? (rows[0].date || '').toString() : ''; })() }}",
                            },
                        ]
                    },
                    "include": "none",
                },
                "name": "Build price window",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.2,
                "position": [860, 320],
            },
            {
                "parameters": {
                    "conditions": {
                        "number": [
                            {
                                "value1": "={{ ($json.rows || []).length }}",
                                "operation": "larger",
                                "value2": 0,
                            }
                        ]
                    },
                    "combineOperation": "all",
                },
                "name": "IF has rows",
                "type": "n8n-nodes-base.if",
                "typeVersion": 1,
                "position": [1080, 440],
            },
            {
                "parameters": {
                    "authentication": "none",
                    "requestMethod": "GET",
                    "url": "={{ 'https://query1.finance.yahoo.com/v8/finance/chart/' + ($items('Set analyzer params (resolved)')[0].json.symbol || 'AAPL.US') + '?range=3mo&interval=1d&events=history' }}",
                    "responseFormat": "json",
                    "options": {
                        "headers": {
                            "User-Agent": "Mozilla/5.0"
                        },
                        "ignoreResponseCode": True
                    },
                },
                "name": "Fetch prices (on-demand)",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 2,
                "position": [1300, 280],
            },
            {
                "parameters": {
                    "mode": "manual",
                    "fields": {
                        "values": [
                            {
                                "name": "symbol",
                                "type": "stringValue",
                                "stringValue": "={{ ($items('Set analyzer params (resolved)')[0].json.symbol || '').toString().trim() }}",
                            },
                            {
                                "name": "lookback",
                                "type": "numberValue",
                                "numberValue": "={{ Number($items('Set analyzer params (resolved)')[0].json.lookback || 60) }}",
                            },
                            {
                                "name": "rows",
                                "type": "arrayValue",
                                "arrayValue": "={{ (() => { const symbol = ($items('Set analyzer params (resolved)')[0].json.symbol || '').toString().trim(); const lookback = Number($items('Set analyzer params (resolved)')[0].json.lookback || 60); const res = $node['Fetch prices (on-demand)'].json?.chart?.result?.[0] || {}; const ts = res.timestamp || []; const quote = (res.indicators && res.indicators.quote && res.indicators.quote[0]) || {}; const rows = ts.map((t, idx) => ({ date: new Date(Number(t) * 1000).toISOString().slice(0,10), open: quote.open?.[idx], high: quote.high?.[idx], low: quote.low?.[idx], close: quote.close?.[idx], volume: quote.volume?.[idx], symbol })).filter(r => r.date); rows.sort((a,b) => b.date.localeCompare(a.date)); return rows.slice(0, lookback); })() }}",
                            },
                            {
                                "name": "as_of",
                                "type": "stringValue",
                                "stringValue": "={{ (() => { const rows = $json.rows || []; return rows.length ? (rows[0].date || '').toString() : ''; })() }}",
                            },
                        ]
                    },
                    "include": "none",
                },
                "name": "Set price window (fetched)",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.2,
                "position": [1740, 280],
            },
            {
                "parameters": {
                    "mode": "manual",
                    "fields": {
                        "values": [
                            {
                                "name": "prompt",
                                "type": "stringValue",
                                "stringValue": "={{ (() => { const symbol = $json.symbol; const asOf = $json.as_of; const rows = $json.rows || []; const csv = rows.map(r => [r.date, r.open, r.high, r.low, r.close, r.volume].join(',')).join('\\n'); return [\n'You are a trading assistant. Analyze daily OHLCV history for one symbol and return ONLY valid JSON (no markdown, no extra text).',\n'Compute SMA20 and SMA60 using the close price over the available rows (if insufficient data, return null for that SMA).',\n'Return fields: symbol, as_of, signal (BUY|SELL|HOLD), confidence (0..1), sma20, sma60, trend (up|down|sideways), summary (Korean, 1-2 sentences).',\n'',\n`symbol: ${symbol}`,\n`as_of: ${asOf}`,\n'',\n'data_csv_header: date,open,high,low,close,volume',\n'data_csv:',\ncsv,\n].join('\\n'); })() }}",
                            }
                        ]
                    },
                    "include": "all",
                },
                "name": "Build prompt",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.2,
                "position": [1300, 440],
            },
            {
                "parameters": {
                    "resource": "text",
                    "operation": "message",
                    "modelId": {
                        "mode": "id",
                        "value": "models/gemini-2.5-flash",
                    },
                    "messages": {
                        "values": [
                            {
                                "content": "={{ $json.prompt }}",
                                "role": "user",
                            }
                        ]
                    },
                    "simplify": True,
                    "jsonOutput": False,
                    "options": {
                        "temperature": 0.2,
                        "includeMergedResponse": True,
                    },
                },
                "name": "Message a model",
                "type": "@n8n/n8n-nodes-langchain.googleGemini",
                "typeVersion": 1.1,
                "position": [1520, 440],
                "credentials": {
                    "googlePalmApi": {
                        "id": "pkuXkUjfGLbb68rB",
                        "name": "Google Gemini(PaLM) Api account",
                    }
                },
            },
            {
                "parameters": {
                    "mode": "manual",
                    "fields": {
                        "values": [
                            {
                                "name": "analysis",
                                "type": "objectValue",
                                "objectValue": "={{ (() => { const text = $json.mergedResponse || $json.content?.parts?.[0]?.text || ''; const clean = text.replace(/```json/g, '').replace(/```/g, '').trim(); let data = {}; try { data = JSON.parse(clean); } catch (e) { data = {}; } return { symbol: data.symbol || $items('Build price window')[0].json.symbol, as_of: data.as_of || $items('Build price window')[0].json.as_of, signal: data.signal || 'HOLD', confidence: data.confidence || 0, summary: data.summary || clean.slice(0, 500), sma20: data.sma20, sma60: data.sma60, trend: data.trend || '' }; })() }}",
                            }
                        ]
                    },
                    "include": "all",
                },
                "name": "Parse analysis JSON",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.2,
                "position": [1740, 440],
            },
            {
                "parameters": {
                    "keepOnlySet": True,
                    "values": {
                        "string": [
                            {"name": "key", "value": "={{ ($items('Build price window')[0].json.symbol || '').toString().trim() + '|gemini' }}"},
                            {"name": "symbol", "value": "={{ ($items('Build price window')[0].json.symbol || '').toString().trim() }}"},
                            {"name": "date", "value": "={{ $json.analysis?.as_of || $items('Build price window')[0].json.as_of || $now.format('yyyy-MM-dd') }}"},
                            {"name": "type", "value": "gemini"},
                            {"name": "value", "value": "={{ ($json.analysis.signal || 'HOLD').toString() }}"},
                            {"name": "threshold", "value": "={{ $json.analysis?.confidence ?? '' }}"},
                            {"name": "message", "value": "={{ ($json.analysis.summary || '').toString() }}"},
                            {"name": "created_at", "value": "={{ new Date().toISOString() }}"},
                        ]
                    },
                },
                "name": "Set signal row (gemini)",
                "type": "n8n-nodes-base.set",
                "typeVersion": 2,
                "position": [1960, 440],
            },
            {
                "parameters": {
                    "respondWith": "json",
                    "responseBody": "={{ $json }}",
                },
                "name": "Respond to Webhook",
                "type": "n8n-nodes-base.respondToWebhook",
                "typeVersion": 1,
                "position": [2180, 350],
            },
            {
                "parameters": {
                    "filePath": SIGNALS_PATH,
                    "dataPropertyName": "data",
                },
                "name": "Read Signals File",
                "type": "n8n-nodes-base.readBinaryFile",
                "typeVersion": 1,
                "position": [2180, 560],
            },
            {
                "parameters": {
                    "operation": "fromFile",
                    "binaryPropertyName": "data",
                    "fileFormat": "xlsx",
                    "options": {
                        "sheetName": "signals",
                        "headerRow": True,
                    },
                },
                "name": "Read Signals Sheet",
                "type": "n8n-nodes-base.spreadsheetFile",
                "typeVersion": 2,
                "position": [2400, 560],
            },
            {
                "parameters": {
                    "mode": "chooseBranch",
                    "numberInputs": 2,
                    "chooseBranchMode": "waitForAll",
                    "output": "empty",
                },
                "name": "Wait for signals data",
                "type": "n8n-nodes-base.merge",
                "typeVersion": 3.2,
                "position": [2620, 440],
            },
            {
                "parameters": {
                    "mode": "manual",
                    "fields": {
                        "values": [
                            {
                                "name": "rows",
                                "type": "arrayValue",
                                "arrayValue": "={{ $items('Set signal row (gemini)').map(i => i.json).concat($items('Read Signals Sheet').map(i => i.json)) }}",
                            }
                        ]
                    },
                    "include": "none",
                },
                "name": "Set combined signals",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.2,
                "position": [2840, 440],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "splitOutItems",
                    "fieldToSplitOut": "rows",
                    "include": "noOtherFields",
                },
                "name": "Split combined signals",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [3060, 440],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "sort",
                    "type": "simple",
                    "sortFieldsUi": {
                        "sortField": [
                            {"fieldName": "created_at", "order": "descending"},
                        ]
                    },
                },
                "name": "Sort signals (new first)",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [3280, 440],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "removeDuplicates",
                    "compare": "selectedFields",
                    "fieldsToCompare": "key",
                },
                "name": "Remove duplicate signals",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [3500, 440],
            },
            {
                "parameters": {
                    "resource": "itemList",
                    "operation": "sort",
                    "type": "simple",
                    "sortFieldsUi": {
                        "sortField": [
                            {"fieldName": "symbol", "order": "ascending"},
                            {"fieldName": "type", "order": "ascending"},
                        ]
                    },
                },
                "name": "Sort signals",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3.1,
                "position": [3720, 440],
            },
            {
                "parameters": {
                    "operation": "toFile",
                    "fileFormat": "xlsx",
                    "binaryPropertyName": "data",
                    "options": {
                        "sheetName": "signals",
                        "headerRow": True,
                        "fileName": "signals.xlsx",
                    },
                },
                "name": "Build signals file",
                "type": "n8n-nodes-base.spreadsheetFile",
                "typeVersion": 2,
                "position": [3940, 440],
            },
            {
                "parameters": {
                    "fileName": SIGNALS_PATH,
                    "dataPropertyName": "data",
                },
                "name": "Write signals file",
                "type": "n8n-nodes-base.writeBinaryFile",
                "typeVersion": 1,
                "position": [4160, 440],
            },
        ],
        "connections": {
            "Manual Trigger": {
                "main": [
                    [
                        {"node": "Set analyzer params", "type": "main", "index": 0},
                        {"node": "Read Prices File", "type": "main", "index": 0},
                    ]
                ]
            },
            "Webhook (analyze)": {
                "main": [
                    [
                        {"node": "Set analyzer params", "type": "main", "index": 0},
                        {"node": "Read Prices File", "type": "main", "index": 0},
                    ]
                ]
            },
            "Set analyzer params": {
                "main": [
                    [
                        {"node": "Set search query (analyzer)", "type": "main", "index": 0},
                    ]
                ]
            },
            "Set search query (analyzer)": {
                "main": [
                    [
                        {"node": "Lookup symbol (analyzer)", "type": "main", "index": 0},
                        {"node": "Wait for symbol (analyzer)", "type": "main", "index": 0},
                    ]
                ]
            },
            "Read Prices File": {
                "main": [[{"node": "Read Prices Sheet", "type": "main", "index": 0}]]
            },
            "Read Prices Sheet": {
                "main": [[{"node": "Wait for price window data", "type": "main", "index": 0}]]
            },
            "Lookup symbol (analyzer)": {
                "main": [[{"node": "Wait for symbol (analyzer)", "type": "main", "index": 1}]]
            },
            "Wait for symbol (analyzer)": {
                "main": [[{"node": "Set analyzer params (resolved)", "type": "main", "index": 0}]]
            },
            "Set analyzer params (resolved)": {
                "main": [[{"node": "Wait for price window data", "type": "main", "index": 1}]]
            },
            "Wait for price window data": {
                "main": [[{"node": "Build price window", "type": "main", "index": 0}]]
            },
            "Build price window": {
                "main": [[{"node": "IF has rows", "type": "main", "index": 0}]]
            },
            "IF has rows": {
                "main": [
                    [{"node": "Build prompt", "type": "main", "index": 0}],
                    [{"node": "Fetch prices (on-demand)", "type": "main", "index": 0}],
                ]
            },
            "Fetch prices (on-demand)": {
                "main": [[{"node": "Set price window (fetched)", "type": "main", "index": 0}]]
            },
            "Set price window (fetched)": {
                "main": [[{"node": "Build prompt", "type": "main", "index": 0}]]
            },
            "Build prompt": {
                "main": [[{"node": "Message a model", "type": "main", "index": 0}]]
            },
            "Message a model": {
                "main": [[{"node": "Parse analysis JSON", "type": "main", "index": 0}]]
            },
            "Parse analysis JSON": {
                "main": [[{"node": "Set signal row (gemini)", "type": "main", "index": 0}]]
            },
            "Read Signals File": {
                "main": [[{"node": "Read Signals Sheet", "type": "main", "index": 0}]]
            },
            "Read Signals Sheet": {
                "main": [[{"node": "Wait for signals data", "type": "main", "index": 1}]]
            },
            "Wait for signals data": {
                "main": [[{"node": "Set combined signals", "type": "main", "index": 0}]]
            },
            "Set combined signals": {
                "main": [[{"node": "Split combined signals", "type": "main", "index": 0}]]
            },
            "Split combined signals": {
                "main": [[{"node": "Sort signals (new first)", "type": "main", "index": 0}]]
            },
            "Sort signals (new first)": {
                "main": [[{"node": "Remove duplicate signals", "type": "main", "index": 0}]]
            },
            "Remove duplicate signals": {
                "main": [[{"node": "Sort signals", "type": "main", "index": 0}]]
            },
            "Sort signals": {
                "main": [[{"node": "Build signals file", "type": "main", "index": 0}]]
            },
            "Build signals file": {
                "main": [[{"node": "Write signals file", "type": "main", "index": 0}]]
            },
            "Set signal row (gemini)": {
                "main": [
                    [
                        {"node": "Read Signals File", "type": "main", "index": 0},
                        {"node": "Wait for signals data", "type": "main", "index": 0},
                        {"node": "Respond to Webhook", "type": "main", "index": 0},
                    ]
                ]
            },
        },
        "settings": {"timezone": "Asia/Seoul", "errorWorkflow": error_workflow_id},
    }


def main():
    api_key = load_api_key()

    error_workflow = upsert_workflow(api_key, WORKFLOW_B_NAME, build_error_workflow())
    error_workflow_id = error_workflow["id"]

    collector_workflow = upsert_workflow(
        api_key, WORKFLOW_A_NAME, build_collector_workflow(error_workflow_id)
    )

    analyzer_workflow = upsert_workflow(
        api_key,
        WORKFLOW_C_NAME,
        build_gemini_analyzer_workflow(error_workflow_id),
        activate=True,
    )

    print("Created/updated workflows:")
    print(f"- {WORKFLOW_B_NAME}: {error_workflow['id']}")
    print(f"- {WORKFLOW_A_NAME}: {collector_workflow['id']}")
    print(f"- {WORKFLOW_C_NAME}: {analyzer_workflow['id']}")


if __name__ == "__main__":
    main()
