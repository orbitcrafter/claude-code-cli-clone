# 에이전트 코어 루프 (Agent Core Loop)

> **한 줄 요약**: 모델에게 도구를 쥐여주고, 모델이 도구를 다 쓸 때까지 도는 while 루프.

---

## 1. 개념의 본질

에이전트(agent)라는 단어는 거창하게 들리지만, 그 심장부는 단 하나의 while 루프다.
"LLM + 도구"의 조합을 반복적으로 순환시켜, 모델이 스스로 판단하고 행동을 선택하게 만드는 것이 전부다.

```
state = [user_message]
while True:
    response = model(state, tools=TOOLS)      # 1. 모델 호출
    state.append(response)
    if response.has_tool_calls():             # 2. 도구 쓰겠다고 했나?
        for call in response.tool_calls:
            result = run_tool(call)           # 3. 실제로 실행
            state.append(result)             # 4. 결과를 다시 넣음
        continue                             # → 루프 처음으로 (반복)
    else:
        break                                # 도구 없음 = 최종 답변
```

이 구조는 언어(Python/Kotlin/TypeScript)나 플랫폼에 관계없이 동일하다.
Claude Code, Cursor, OpenAI Codex, 모두 이 루프 위에 쌓인 앱이다.

---

## 2. 루프의 4단계 해부

### 2-1. 모델 호출 (Step 1)

```kotlin
val response = client.createMessage(
    model = currentModel,
    messages = state,           // 누적된 전체 대화 이력
    tools = TOOLS,              // 사용 가능한 도구 목록
    maxTokens = 8192
)
```

- **state**: 지금까지의 모든 메시지(user + assistant + tool_result)를 담은 배열.
  모델은 매 호출마다 이 배열 전체를 context window에 올려서 읽는다.
- **tools**: 모델이 선택할 수 있는 도구의 스키마 목록. 모델은 이것을 "메뉴판"처럼 읽는다.
- 모델은 **무상태(stateless)**다. 이전 대화를 기억하지 않으며, 매번 state 전체를 새로 받아 판단한다.

### 2-2. 도구 호출 여부 판단 (Step 2)

모델의 응답에는 두 가지 타입이 있다:

| 응답 타입 | 의미 | 루프 동작 |
|---|---|---|
| `text` 블록만 있음 | 최종 답변, 더 할 일 없음 | **루프 종료 (break)** |
| `tool_use` 블록 있음 | 도구를 실행하고 싶다는 의사 표현 | **계속 (continue)** |

중요한 점: 모델은 "실행하겠다"가 아니라 "실행하고 싶다"고 **의사를 표현**할 뿐이다.
실제 실행권은 항상 우리 코드(harness)에 있다. 이것이 안전장치의 근거다.

### 2-3. 도구 실행 (Step 3)

```kotlin
fun runTool(call: ToolUse): ToolResult {
    return when (call.name) {
        "read_file"  -> readFile(call.input["path"]!!)
        "run_bash"   -> runBash(call.input["command"]!!)
        "write_file" -> writeFile(call.input["path"]!!, call.input["content"]!!)
        else -> ToolResult(toolUseId = call.id, content = "Unknown tool: ${call.name}")
    }
}
```

- `run_tool`은 단순한 dispatcher다. 도구 이름을 보고 해당 함수를 호출한다.
- 도구 실행 결과는 문자열(또는 구조화 데이터)로 반환된다.

### 2-4. 결과 주입 (Step 4)

```kotlin
state += Message(
    role = "user",
    content = listOf(
        ContentBlock.ToolResult(
            toolUseId = call.id,
            content = result
        )
    )
)
```

- 결과를 state에 추가할 때 role은 `"user"`다(Anthropic API 규약).
- 루프 처음으로 돌아가 모델이 결과를 보고 다음 행동을 결정한다.

---

## 3. 실제 실행 흐름 예시

"현재 디렉터리에 있는 파일들을 나열하고, README.md가 있으면 내용을 읽어줘"

```
Turn 1
  user: "현재 디렉터리에 있는 파일들을 나열하고, README.md가 있으면 내용을 읽어줘"
  model → tool_use: list_dir(path=".")

Turn 2 (도구 실행 후)
  tool_result: "README.md\nsrc/\nbuild.gradle.kts"
  model → tool_use: read_file(path="README.md")

Turn 3 (도구 실행 후)
  tool_result: "# My Project\n..."
  model → text: "현재 디렉터리에는 README.md, src/, build.gradle.kts가 있습니다.
                  README.md 내용은 다음과 같습니다: ..."

루프 종료 (tool_use 없음)
```

루프가 **3회** 돌았다. 각 회차가 하나의 "생각 → 행동 → 관찰" 사이클이다.

---

## 4. ReAct 패턴과의 관계

이 루프는 학술적으로 **ReAct (Reasoning + Acting)** 패턴이라고 불린다.

```
Thought:  나는 디렉터리를 먼저 봐야 한다
Act:      list_dir(".")
Observe:  README.md가 있다
Thought:  이제 README.md를 읽어야 한다
Act:      read_file("README.md")
Observe:  내용이 "# My Project..."다
Thought:  이제 답변할 수 있다
Answer:   "현재 디렉터리에는..."
```

모델의 "생각(reasoning)"이 tool_use 선택으로, "행동(acting)"이 run_tool 실행으로, "관찰(observing)"이 tool_result 주입으로 구현된다.

---

## 5. 루프의 종료 조건

| 종료 원인 | 설명 |
|---|---|
| **정상 종료** | 모델이 tool_use 없이 text만 반환 |
| **최대 턴 초과** | 안전장치: 루프 횟수 제한 (예: 20회) |
| **컨텍스트 한계** | state가 context window를 초과 |
| **오류 발생** | 도구 실행 실패, API 오류 |
| **사용자 중단** | Ctrl+C 등 인터럽트 |

실제 구현에서는 무한 루프 방지를 위해 반드시 최대 턴 수 제한이 필요하다.

---

## 6. 코어 루프가 전부인 이유

모든 에이전트 기능은 이 루프의 어딘가에 붙는다:

| 기능 | 루프에서의 위치 |
|---|---|
| 세션 | state를 디스크에 저장/복원 |
| 컴팩트 | state가 길어지면 summarize 호출로 압축 |
| 서브에이전트 | run_tool 내에서 별도 state로 agent() 재호출 |
| 훅 | run_tool 전/후에 끼우는 콜백 |
| 룰 | state 앞에 항상 붙는 system 프롬프트 |
| 안전장치 | run_tool 전에 사용자 확인을 받는 게이트 |

"마법은 한 층도 없다. 전부 while 루프 위의 엔지니어링 결정이다."

---

## 7. Kotlin 구현 골격

```kotlin
sealed interface ContentBlock {
    data class Text(val text: String) : ContentBlock
    data class ToolUse(
        val id: String,
        val name: String,
        val input: JsonObject
    ) : ContentBlock
    data class ToolResult(
        val toolUseId: String,
        val content: String
    ) : ContentBlock
}

data class Message(
    val role: String,        // "user" | "assistant"
    val content: List<ContentBlock>
)

suspend fun agent(
    userMessage: String,
    client: AnthropicClient,
    tools: List<Tool>,
    maxTurns: Int = 20
) {
    val state = mutableListOf(Message.user(userMessage))
    var turns = 0

    while (turns++ < maxTurns) {
        val response = client.createMessage(state, tools)    // Step 1
        state += response.toAssistantMessage()

        val toolUses = response.content.filterIsInstance<ContentBlock.ToolUse>()
        if (toolUses.isEmpty()) break                         // Step 2: 종료

        val results = toolUses.map { runTool(it) }           // Step 3: 실행
        state += Message.toolResults(results)                 // Step 4: 주입
    }
}
```

---

## 8. 주요 설계 결정들

### 왜 state를 매번 전부 보내는가?

모델은 무상태이므로 이전 대화를 알 방법이 없다. 매 호출에 전체 이력을 보내는 것이 유일한 방법이다.
이것이 컨텍스트 윈도우가 중요한 이유이고, compaction이 필요한 이유다.

### 왜 tool_result의 role이 "user"인가?

Anthropic API의 messages 포맷에서 대화는 반드시 user → assistant → user → assistant...로 교대해야 한다. 도구 실행 결과를 다시 모델에게 넘기는 것은 "사용자(harness)가 모델에게 보내는 정보"이므로 role이 "user"다.

### 왜 한 번의 응답에 여러 tool_use가 올 수 있는가?

모델이 병렬 실행 가능한 도구들을 한 번에 요청할 수 있다. 예: 두 파일을 동시에 읽는 것. Harness는 이것들을 병렬로 실행해서 모두 완료된 뒤 results를 한꺼번에 주입할 수 있다.

---

## References

- [Anthropic Tool Use Documentation](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al., 2022)](https://arxiv.org/abs/2210.03629)
- [Anthropic Messages API Reference](https://docs.anthropic.com/en/api/messages)
- [OpenAI Function Calling (같은 패턴의 다른 구현)](https://platform.openai.com/docs/guides/function-calling)
- [LangChain AgentExecutor (동일 개념의 Python 구현 참고)](https://python.langchain.com/docs/how_to/agent_executor/)
