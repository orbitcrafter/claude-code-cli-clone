# bomini 개념 문서 인덱스

> 지하철에서 읽는 용. 각 파일은 하나의 개념을 독립적으로 다룬다.

---

## 코어 (Phase 1)

| 문서 | 핵심 한 줄 |
|---|---|
| [01-agent-core-loop.md](01-agent-core-loop.md) | while 루프. 모든 에이전트의 심장 |
| [02-anthropic-api-client.md](02-anthropic-api-client.md) | POST /v1/messages. 앱 = HTTP 클라이언트 |
| [03-tool-system.md](03-tool-system.md) | 도구 = 스키마 + 구현. 모델은 의사만 표현 |
| [04-streaming.md](04-streaming.md) | SSE로 토큰 단위 실시간 출력 |

## 도구들 (Phase 1-2)

| 문서 | 핵심 한 줄 |
|---|---|
| [05-file-tools.md](05-file-tools.md) | read/write/edit/list. 파일시스템 4총사 |
| [06-bash-tool.md](06-bash-tool.md) | 에이전트에게 터미널을 쥐여주는 도구 |
| [07-search-tools.md](07-search-tools.md) | grep으로 먼저 위치 찾고, 그다음 read |

## 세션 & 컨텍스트 (Phase 3)

| 문서 | 핵심 한 줄 |
|---|---|
| [08-session-persistence.md](08-session-persistence.md) | state를 JSON으로 저장/복원 |
| [09-context-window.md](09-context-window.md) | 200K 토큰 한계. 비용의 근원 |
| [10-compaction.md](10-compaction.md) | 오래된 대화를 요약으로 압축. 정보는 손실된다 |

## 멀티 에이전트 (Phase 4)

| 문서 | 핵심 한 줄 |
|---|---|
| [11-sub-agents.md](11-sub-agents.md) | run_tool 안에서 agent()를 다시 호출 |
| [12-agent-teams.md](12-agent-teams.md) | 여러 서브에이전트 병렬/순차 오케스트레이션 |

## 제어 층 (Phase 5)

| 문서 | 핵심 한 줄 |
|---|---|
| [13-rules.md](13-rules.md) | BOMINI.md → system 프롬프트에 자동 주입 |
| [14-hooks.md](14-hooks.md) | 도구 전/후에 끼우는 LLM 무관 콜백 |
| [15-skills.md](15-skills.md) | description + 파일경로. 모델이 확률적으로 호출 |
| [16-model-selection.md](16-model-selection.md) | model= 문자열 하나를 바꾸는 것 |
| [20-slash-commands.md](20-slash-commands.md) | LLM 없이 harness가 직접 처리하는 커맨드 |

## 안전 & UX (Phase 6)

| 문서 | 핵심 한 줄 |
|---|---|
| [17-safety-gates.md](17-safety-gates.md) | run_tool 전에 위험 동작을 사용자에게 확인 |
| [18-terminal-ui.md](18-terminal-ui.md) | println → ANSI → Mordant 순으로 보강 |

## 외부 연결

| 문서 | 핵심 한 줄 |
|---|---|
| [19-mcp.md](19-mcp.md) | AI ↔ 외부 도구 연결 표준. JSON-RPC 2.0 기반 |

---

## 읽는 순서 추천

처음 읽는다면:
1. `01` → `03` → `02` → `04` (코어 루프 → 도구 → API → 스트리밍)
2. `05` → `06` → `07` (각 도구)
3. `08` → `09` → `10` (세션, 컨텍스트, 압축)
4. `11` → `12` (멀티 에이전트)
5. `13` → `14` → `15` → `16` (제어 층)
6. `17` → `18` (안전, UI)
7. `19` → `20` (MCP, 슬래시 커맨드)

복습한다면 관심 있는 것부터 독립적으로 읽어도 된다.
