# CLAUDE.md — `bomini` 프로젝트 개발 가이드

> 이 파일은 Claude Code가 이 레포에서 작업할 때 항상 먼저 읽는 프로젝트 가이드다.
> 프로젝트의 목표, 멘탈 모델, 설계 원칙, 구현 로드맵, 작업 규칙을 담는다.
> (만들 앱 이름: **`bomini`** / 앱이 읽을 규칙 파일: **`BOMINI.md`**)

## 0. 이 프로젝트가 무엇인가

**만들 앱 이름: `bomini`** (터미널 명령어도 `bomini`)
**우리 앱이 로드할 규칙 파일 이름: `BOMINI.md`**

> 이름에 대한 중요한 구분:
> - 이 문서(`CLAUDE.md`)는 **내가 Claude Code로 이 프로젝트를 개발할 때** Claude Code가 읽는 가이드다. 이름 그대로 둔다.
> - `BOMINI.md`는 **우리가 만드는 앱 `bomini`가 실행 시 읽어 system 프롬프트에 주입할** 규칙 파일이다.
    >   (즉 `claude` ↔ `CLAUDE.md` 구조를 그대로 미러링한 것: `bomini` ↔ `BOMINI.md`)
> - 둘을 헷갈리지 말 것. 전자는 개발용, 후자는 우리 앱이 구현할 기능의 대상 파일.

`bomini`는 **Claude Code CLI와 동일한 방식으로 동작하는, 터미널용 코딩 에이전트**다.
즉 어떤 터미널에서든 `bomini`로 실행되어, 대화형으로 코드를 읽고/고치고/실행하며,
세션·별도 컨텍스트·서브에이전트·룰(BOMINI.md 로드)·훅·스킬·모델 선택 등을 모두 갖춘다.

이 프로젝트는 그런 `bomini`를 **제로베이스에서 직접 만들어** 그 내부 동작을 완전히 이해하는 학습용 프로젝트다.

목표는 "Claude Code의 상용 클론을 완성하는 것"이 **아니다**.
목표는 **에이전트의 코어 루프와 각 기능이 코드의 어느 지점에 어떻게 붙는지를
내 손으로 재현해서 블랙박스를 걷어내는 것**이다.
(동작 메커니즘은 Claude Code와 동일하게 재현하되, 내부 세부 구현과 모델-harness 공동 튜닝까지
똑같아지는 것은 아니다 — "원리는 동일, 마감 세부는 우리 방식".)

따라서 이 레포의 모든 결정에서 다음이 우선한다:
- 동작하는 최소 구현 > 완성도 높은 기능
- 메커니즘이 드러나는 코드 > 추상화로 감춰진 코드
- "왜 이렇게 설계하는가"를 주석/문서로 남기기 > 깔끔하지만 설명 없는 코드

## 1. 핵심 멘탈 모델 (이 프로젝트의 헌법)

에이전트의 본질은 단 한 문장이다:

> **모델에게 도구를 쥐여주고, 모델이 도구를 다 쓸 때까지 도는 while 루프.**

코어 루프는 4단계의 반복이다:
1. 모델 호출 — 현재까지의 상태(state) 전체 + 도구 목록을 넘긴다
2. 모델이 "이 도구를 이 인자로 부르고 싶다"고 하면 → 그 도구를 실제로 실행한다
3. 실행 결과를 state에 다시 넣는다
4. 루프 처음으로 돌아간다. 모델이 더 이상 도구를 안 부르면 종료(= 최종 답변)

```
state = [user_message]
while True:
    response = model(state, tools=TOOLS)      # 1. 모델 호출
    state.append(response)
    if response.has_tool_calls():             # 2. 도구 쓰겠다고 했나?
        for call in response.tool_calls:
            result = run_tool(call)            # 3. 실제로 실행
            state.append(result)               # 4. 결과를 다시 넣음
        continue                               #    → 루프 처음으로 (반복)
    else:
        break                                  # 도구 없음 = 최종 답변
```

**Claude Code, Cursor, Codex는 전부 이 루프 위에 쌓인 앱이다.**
언어(TS/Python/Rust/Kotlin)도, UI도, 기능 이름도 다르지만 심장은 동일하다.
모델은 클라우드의 API로 호출하는 외부 자원이고, 이 앱은 그 API의 **클라이언트**일 뿐이다.
> 위 의사코드는 언어 무관 개념도다. 이 프로젝트의 실제 코틀린 골격은 §4 참고.

### 모든 기능은 이 루프의 어느 지점에 붙는가 (구현의 지도)

이 매핑이 이 프로젝트 전체의 설계도다. 새 기능을 구현할 때 항상 "이건 루프의 어디에 붙는가"를 먼저 답한다.

| 기능 | 코어 루프에서의 위치 / 정체 |
|---|---|
| **도구(tool)** | `run_tool` 함수 본체. 모델은 "부르겠다"는 의사만 표현, 실행은 우리 코드 |
| **세션(session)** | `state`(누적 메시지 배열)를 저장/복원하는 것 |
| **별도 컨텍스트** | 서브에이전트마다 독립된 `state`를 갖는 것 (격리) |
| **서브에이전트(sub-agent)** | `run_tool` 안에서 별도 state로 `agent()`를 다시 호출. 도구처럼 보이는 또 다른 루프 |
| **에이전트 팀(agent team)** | 서브에이전트가 여럿이고, 메인이 그들을 오케스트레이션 |
| **훅(hook)** | `run_tool` 호출 직전/직후, 세션 시작/종료 등에 끼우는 콜백. LLM 무관 순수 코드 |
| **룰(rules)** | `messages` 맨 앞에 매번 자동으로 붙는 system 프롬프트 텍스트 |
| **컴팩트(compaction)** | `state`가 길어지면 "요약해줘"로 모델을 한 번 더 호출해 긴 state를 짧게 치환 |
| **모델 선택/라우팅** | API 호출 시 `model=` 문자열을 작업별로 바꾸는 것 |
| **스킬(skill)** | TOOLS에 "description + 파일경로" 항목 추가. 모델이 description 보고 읽을지 판단 |
| **승인/안전장치** | `run_tool` 실행 전에 위험 동작을 가로채 사용자 확인을 받는 게이트 |

**마법은 한 층도 없다. 전부 while 루프 위의 엔지니어링 결정이다.**
이 사실을 코드로 계속 확인하는 것이 이 프로젝트의 핵심 학습이다.

## 2. 빠짐없이 구현할 기능 목록 (Claude Code 기준, 하나도 빼지 않음)

아래는 전부 구현 대상이다. 단, 한 번에 다 만들지 않고 §3 로드맵 순서로 쌓아 올린다.

### 코어
- [ ] 에이전트 코어 루프 (모델 호출 → 도구 실행 → 결과 주입 → 반복)
- [ ] 모델 API 클라이언트 (Anthropic API 호출, 인증, 에러/재시도 처리)
- [ ] 도구 정의(스키마) + 도구 실행 디스패처
- [ ] 스트리밍 응답 처리 (토큰 단위 출력)

### 도구 세트
- [ ] `read_file` — 파일 읽기
- [ ] `write_file` — 파일 쓰기
- [ ] `edit_file` — 정밀 편집(통째 덮어쓰기가 아니라 부분 치환/diff)
- [ ] `list_dir` — 디렉터리 나열
- [ ] `run_bash` — 셸 명령 실행
- [ ] `grep` / `search` — 코드베이스 검색
- [ ] (선택) 코드베이스 인덱싱 기반 의미 검색
- [ ] 웹 검색/페치 (선택)

### 세션 & 컨텍스트
- [ ] 세션 영속화 (state를 디스크에 저장/복원, 세션 ID, 이어가기/resume)
- [ ] 세션 목록/전환
- [ ] 컨텍스트 윈도우 관리 (토큰 추정, 한계 근접 감지)
- [ ] **컴팩트(compaction)** — 긴 대화를 요약 호출로 압축, 디테일 손실 지점 관찰
- [ ] 컨텍스트 선택 로직 — 어떤 파일/내용을 프롬프트에 넣을지 결정

### 멀티 에이전트
- [ ] **서브에이전트** — 격리된 별도 컨텍스트에서 작업, 최종 요약만 반환
- [ ] **에이전트 팀** — 여러 서브에이전트 오케스트레이션, 결과 종합

### 확장/제어
- [ ] **룰(rules)** — `BOMINI.md`(우리 앱의 프로젝트 규칙 파일)를 읽어 system 프롬프트에 자동 주입
- [ ] **훅(hooks)** — 도구 실행 전/후, 세션 시작/종료 등 라이프사이클 콜백
- [ ] **스킬(skills)** — description+경로로 등록, 모델이 필요 시 읽는 가이드 파일
- [ ] **모델 선택/라우팅** — 두 방식 모두 구현:
    - (1) **사용자 선택**: Claude Code CLI의 `/model`처럼, 명령으로 Opus/Sonnet/Haiku를
      직접 골라 세션에 적용하고 전환. 현재 모델을 상태로 보관하고 다음 호출부터 반영.
    - (2) **자동 라우팅**: 작업 복잡도에 따라 앱이 모델을 자동 선택 (싼/빠른 vs 강한)
    - 둘 다 결국 API 호출의 `model` 문자열을 바꾸는 것 — UI/명령은 그 위의 얇은 껍데기
- [ ] 슬래시 커맨드 / 커스텀 커맨드 (선택)
- [ ] MCP 류 외부 도구 연결 (선택, 후순위)

### 안전 & UX
- [ ] 도구 실행 전 사용자 승인 게이트 (특히 파일 삭제/덮어쓰기/위험 bash)
- [ ] 위험 동작 차단/경고
- [ ] 터미널 UI (대화 렌더링, diff 미리보기, 진행 표시)
- [ ] 비용/토큰 사용량 표시

## 3. 구현 로드맵 (이 순서로 쌓는다)

각 Phase는 **그 자체로 돌아가는 것**을 목표로 한다. 다음 Phase로 넘어가기 전에 직접 돌려본다.

### Phase 1 — 심장 (반나절~하루)
코어 루프 + `run_bash` + `read_file` + `write_file`.
이것만으로 "코드 짜줘 → 실제로 파일 생성"이 되는 미니 에이전트가 된다.
> 완료 기준: 여러 단계가 필요한 작업(예: 파일 만들고 → 줄 수 세기)을 시키면
> 루프가 2회 이상 돌며 스스로 끝까지 수행하고 종료한다.
> 인증/API 배관에서 시간을 많이 쓰게 됨을 받아들인다 — 본질(루프)은 짧다.

### Phase 2 — 도구 확장 + 스킬 실험
`list_dir`, `grep`, `edit_file`(정밀 편집) 추가.
스킬 항목을 TOOLS에 넣고, **description 문구를 바꿔가며 호출률이 달라지는 걸 직접 관찰**한다.
> 이 프로젝트의 출발점이 된 원래 질문 — "스킬이 왜 어떨 땐 호출되고 어떨 땐 안 되나" —
> 의 답을 여기서 손으로 확인한다. 호출 여부는 결정론이 아니라 모델의 확률적 판단이다.

### Phase 3 — 세션 & 컴팩트
state를 디스크에 저장/복원(세션), 이어가기.
대화가 길어지면 요약 호출로 압축하는 compaction 구현.
> 완료 기준: 긴 세션을 컴팩트한 뒤 "방금 전에 뭐 했지?"를 물어
> **디테일이 어떻게 손실되는지**를 직접 본다. (컴팩트 후 맥락 상실의 정체)

### Phase 4 — 멀티 에이전트
`run_tool` 안에서 격리된 state로 `agent()`를 재호출 = 서브에이전트.
여러 개로 확장 = 에이전트 팀.
> 완료 기준: 메인 에이전트가 서브에게 작업을 위임하고,
> 서브의 긴 작업 과정은 안 받고 **최종 요약만** 결과로 받는 구조를 확인한다.

### Phase 5 — 제어 층 (룰 / 훅 / 모델 선택·라우팅)
CLAUDE.md... 가 아니라 **`BOMINI.md`**(우리 앱의 규칙 파일)를 읽어 system 프롬프트에 주입(룰).
도구 실행 전/후 콜백(훅).
모델 선택: Claude Code CLI의 `/model`처럼 사용자가 명령으로 Opus/Sonnet/Haiku를 전환 +
작업별 자동 라우팅.
> 여기까지 오면 이 기능들이 "코어 위의 얇은 층"임이 코드로 자명해진다.
> 특히 `/model`로 모델을 바꿔도 바뀌는 건 API 호출의 `model` 문자열 하나뿐임을 확인한다.

### Phase 6 — 안전 & UX 마감
승인 게이트, 위험 동작 차단, 터미널 UI, 토큰/비용 표시.
> harness의 "바깥 층". 본질 이해 후 완성도를 높이는 단계.

## 4. 기술 스택 / 구조 결정 (확정: Kotlin)

- **언어**: **Kotlin (JVM)**. 개발자 주력 언어라 문법 마찰 없이 본질에 집중 가능.
    - 코루틴 → 스트리밍 응답, 서브에이전트 동시 실행에 적합
    - sealed class / data class → 모델 응답 블록(text / tool_use / tool_result)과
      도구 정의를 타입 안전하게 표현
- **빌드**: Gradle (Kotlin DSL, `build.gradle.kts`). 시작은 JVM 콘솔 앱.
  (네이티브 바이너리가 필요해지면 나중에 GraalVM/Kotlin-Native 검토. 초반엔 JVM이 마찰 최소)
- **모델 호출**: **공식 코틀린 SDK에 의존하지 않고 HTTP로 직접 호출**한다.
    - 엔드포인트: `POST https://api.anthropic.com/v1/messages`
    - 헤더: `x-api-key: $ANTHROPIC_API_KEY`, `anthropic-version: <버전>`, `content-type: application/json`
    - HTTP 클라이언트: **Ktor client**(코루틴 친화) 또는 OkHttp 중 택1
    - 이유: SDK가 감싸주는 걸 직접 봄으로써 "앱은 모델 API의 클라이언트일 뿐"을 체감.
    - 시작 시 코틀린용 1차 SDK 존재 여부를 한 번 검색 확인할 것(없다고 가정하고 직접 호출이 기본).
- **JSON 직렬화**: `kotlinx.serialization`. 도구 스키마, 요청/응답 바디를 타입으로 관리.
- **모델 선택**: 모델 문자열(예: Opus/Sonnet/Haiku 각각의 model id)을 enum 또는 상수로 두고,
  세션 상태에 "현재 모델"을 보관. `/model` 명령으로 전환하면 다음 API 호출부터 반영.
  (= API 호출의 `model` 필드만 바뀌는 것)
- **상태 저장**: 처음엔 JSON 파일로 단순하게(kotlinx.serialization). 필요해지면 SQLite 등으로.
- **CLI 실행**: 어떤 터미널에서든 `bomini` 명령으로 실행. 초반엔 Gradle `application` 플러그인이
  생성하는 실행 스크립트 또는 PATH에 둔 래퍼 스크립트로 충분. 후반 선택지로 GraalVM native-image.
- **터미널 UI**: 초반엔 `println`으로 충분. Phase 6에서 Mordant 등으로 색상/diff/진행 표시 보강.

권장 디렉터리 구조(Gradle/코틀린 관례, 패키지는 예: `dev.bomini`):
```
build.gradle.kts
settings.gradle.kts
CLAUDE.md                      # 이 파일 (Claude Code가 읽는 개발 가이드)
BOMINI.md                      # bomini 앱이 실행 시 읽는 규칙 파일 (= 룰 기능의 대상)
/src/main/kotlin/dev/bomini/
  core/        # 코어 루프(Agent.kt), 모델 HTTP 클라이언트(AnthropicClient.kt)
  model/       # 요청/응답 data class, ContentBlock sealed class, Model enum
  tools/       # 도구 정의(Tool.kt) + 실행 디스패처 (ReadFile, RunBash, EditFile, Grep ...)
  session/     # 세션 영속화, 컨텍스트 관리, compaction
  agents/      # 서브에이전트, 에이전트 팀
  control/     # 룰(BOMINI.md 로드), 훅, 모델 선택/라우팅
  ui/          # 터미널 렌더링, diff, 승인 프롬프트
  safety/      # 승인 게이트, 위험 동작 차단
  Main.kt      # 진입점 (터미널 REPL 루프)
/sessions      # 저장된 세션 (JSON)
/skills        # 스킬 가이드 파일들
```

코어 루프의 코틀린 골격(개념 스케치 — Phase 1에서 실제 구현):
```kotlin
// ContentBlock: 모델 응답/도구결과를 sealed로 표현
sealed interface ContentBlock {
    data class Text(val text: String) : ContentBlock
    data class ToolUse(val id: String, val name: String, val input: JsonObject) : ContentBlock
    data class ToolResult(val toolUseId: String, val content: String) : ContentBlock
}

suspend fun agent(userMessage: String, client: AnthropicClient, tools: List<Tool>) {
    val state = mutableListOf<Message>(Message.user(userMessage))   // 누적 state = 세션
    while (true) {
        val resp = client.create(state, tools, model = currentModel) // 1. 모델 호출
        state += resp.toAssistantMessage()
        val toolUses = resp.content.filterIsInstance<ContentBlock.ToolUse>()
        if (toolUses.isEmpty()) break                                // 도구 없음 = 최종 답변
        val results = toolUses.map { runTool(it, tools) }            // 2~3. 실제 실행
        state += Message.toolResults(results)                        // 4. 결과 주입
        // → while 처음으로 (반복)
    }
}
```

## 5. Claude(너)가 이 레포에서 작업할 때의 규칙

1. **항상 멘탈 모델 먼저.** 새 기능을 만들기 전에 "이건 §1 코어 루프의 어디에 붙는가"를
   한 문장으로 답하고 시작한다. 답이 안 나오면 설계가 틀린 것이다.
2. **학습이 목적이다.** 영리한 추상화로 메커니즘을 숨기지 말 것.
   루프와 도구가 코드에서 눈에 보이게 유지한다. "왜 이렇게 했는가" 주석을 남긴다.
3. **Phase 순서를 지킨다.** 사용자가 명시적으로 건너뛰라 하지 않는 한,
   현재 Phase가 실제로 돌아가는 걸 확인하기 전에 다음 Phase로 넘어가지 않는다.
4. **한 번에 다 만들지 않는다.** "전부 구현"은 최종 목표이지 한 커밋의 목표가 아니다.
   작은, 돌아가는 단위로 쪼개 제안한다.
5. **막히는 지점을 학습 포인트로 다룬다.** 특히 API 인증, 컨텍스트 한계, compaction의
   디테일 손실 같은 "현실의 마찰"은 버그가 아니라 이해해야 할 본질이다. 그 지점에서 멈춰 설명한다.
6. **모델/도구 호출의 비결정성을 인정한다.** 같은 입력에 결과가 갈리는 건 정상이다.
   결정론적 분기처럼 설명하지 않는다.
7. **안전 동작은 진짜로 구현한다.** 파일 삭제·덮어쓰기·위험 bash는 승인 게이트를 거치게 한다
   (이 앱 자체가 실제로 내 파일시스템을 만지므로).

## 6. 용어 메모

- **harness**: 모델을 둘러싼 앱 전체(루프·도구·컨텍스트 관리·UI). 경쟁우위의 주 전장.
- **frontier model**: 능력 최전선의 대규모 범용 모델. 가중치는 보통 비공개(closed),
  API로 출력만 빌려줌. 이 앱은 그 API의 클라이언트다.
- **state / context**: 누적된 메시지 배열. 길어지면 컨텍스트 윈도우를 채우고 compaction 대상이 됨.

---
*이 문서는 살아있는 설계도다. 구현하며 알게 된 것을 계속 이 파일에 반영한다.*