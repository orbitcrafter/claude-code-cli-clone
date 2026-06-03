# 서브에이전트 (Sub-Agent)

> **한 줄 요약**: `run_tool()` 안에서 별도의 state로 `agent()`를 다시 호출하는 것.
> 도구처럼 보이는 또 다른 에이전트 루프다.

---

## 1. 서브에이전트의 본질

일반 도구(`read_file`, `run_bash`)는:
```
모델 → tool_use → 단순 함수 실행 → 결과 반환
```

서브에이전트는:
```
메인 모델 → tool_use("sub_agent") → [별도 루프 시작]
                                         서브 모델 → tool_use → 실행
                                         서브 모델 → tool_use → 실행
                                         서브 모델 → 최종 답변
                                     [별도 루프 종료] → 요약만 반환
             ← 요약 결과
```

서브에이전트는 **격리된 별도의 state**를 가진다.
메인 에이전트는 서브에이전트의 내부 과정을 알 필요 없고,
최종 결과(요약)만 받는다.

---

## 2. 왜 서브에이전트를 쓰는가

### 문제 분해 (Decomposition)

큰 작업을 서브에이전트에게 위임하면:
1. **컨텍스트 격리**: 서브에이전트의 긴 작업 과정이 메인 context를 오염시키지 않는다
2. **병렬 실행**: 여러 서브에이전트가 동시에 작업 가능
3. **재사용**: 특정 목적(검색, 코드 리뷰 등)의 서브에이전트를 반복 사용 가능
4. **전문화**: 서브에이전트마다 다른 system prompt, 다른 도구 세트 적용 가능

### 예시

```
메인 에이전트: "이 프로젝트의 모든 TODO를 찾아서 우선순위별로 정리해줘"
  
  → 서브에이전트 1: "src/ 디렉터리에서 TODO 찾기"
      grep("TODO", "src/")
      read_file("src/A.kt")
      read_file("src/B.kt")
      ... (내부 과정 50개 턴)
      → "발견된 TODO 15개: [목록]"
  
  → 서브에이전트 2: "test/ 디렉터리에서 TODO 찾기"
      ... (내부 과정)
      → "발견된 TODO 8개: [목록]"
  
  메인 에이전트: 두 결과를 합쳐서 우선순위별로 정리 → 최종 답변
```

메인 에이전트의 state에는 서브에이전트의 50턴 작업 과정이 들어오지 않고,
요약 결과만 들어온다.

---

## 3. 구현: 서브에이전트는 도구다

서브에이전트는 `run_tool()` 안에서 `agent()`를 재귀 호출하는 것으로 구현된다:

```kotlin
// 서브에이전트 도구 스키마
val SUB_AGENT_TOOL = Tool(
    name = "spawn_sub_agent",
    description = """Spawn an isolated sub-agent to handle a specific task.
        The sub-agent has its own context and runs independently.
        Only the final result is returned — the sub-agent's work process
        is not visible to the main context.
        Use for complex multi-step sub-tasks that would pollute the main context.""",
    inputSchema = ToolInputSchema(
        properties = mapOf(
            "task" to PropertySchema("string", "Clear description of what the sub-agent should do"),
            "tools" to PropertySchema("array", "List of tool names the sub-agent can use"),
            "model" to PropertySchema("string", "Model to use for sub-agent (optional)")
        ),
        required = listOf("task")
    )
)

// 도구 디스패처에서 서브에이전트 처리
fun runTool(call: ToolUse): ToolResult {
    return when (call.name) {
        "spawn_sub_agent" -> runSubAgent(call)
        // ... 다른 도구들
    }
}

// 서브에이전트 실행 (별도 state, 별도 루프)
suspend fun runSubAgent(call: ToolUse): ToolResult {
    val task = call.input["task"]!!.jsonPrimitive.content
    val requestedTools = call.input["tools"]?.jsonArray?.map { it.jsonPrimitive.content }
    val model = call.input["model"]?.jsonPrimitive?.content ?: defaultModel
    
    // 서브에이전트용 도구 세트 (제한 가능)
    val subAgentTools = if (requestedTools != null)
        ALL_TOOLS.filter { it.name in requestedTools }
    else ALL_TOOLS
    
    // 격리된 별도 state로 에이전트 루프 실행
    val subState = mutableListOf<Message>(
        Message.system("You are a focused sub-agent. Complete the given task efficiently."),
        Message.user(task)
    )
    
    // 별도 루프 (메인 에이전트의 state와 완전히 분리)
    val result = runAgentLoop(
        state = subState,
        client = client,
        tools = subAgentTools,
        model = model,
        maxTurns = 50
    )
    
    // 서브에이전트의 최종 텍스트 응답만 반환
    return ToolResult(
        toolUseId = call.id,
        content = result.finalText ?: "Sub-agent completed without output"
    )
}
```

---

## 4. 별도 컨텍스트(Isolated Context)의 의미

```kotlin
// 메인 에이전트의 state (40개 메시지 ≈ 30K 토큰)
val mainState = mutableListOf<Message>(...)

// 서브에이전트의 state (완전히 독립적)
val subState = mutableListOf<Message>(
    Message.system("..."),
    Message.user(task)           // 메인 state의 내용이 없음
)

// 서브에이전트가 50턴을 돌아도...
// mainState는 그대로
// subState만 커짐

// 서브에이전트 완료 후
// mainState에는 결과 요약 1개만 추가
mainState.add(ToolResult("spawn_sub_agent", "서브에이전트 결과: ..."))
```

이것이 "격리"의 의미다.

---

## 5. 서브에이전트의 Context 전달

서브에이전트는 독립된 context를 갖지만, 필요한 정보는 task 설명에 포함해야 한다:

```kotlin
// 메인 에이전트가 서브에이전트를 호출할 때
val taskDescription = """
    다음 파일들에서 사용되지 않는 import를 제거해줘:
    - src/main/kotlin/dev/bomini/core/Agent.kt
    - src/main/kotlin/dev/bomini/tools/ReadFile.kt
    
    현재 프로젝트 루트: /Users/dev/my-project
    빌드 도구: Gradle (./gradlew build로 확인 가능)
"""

// 서브에이전트는 이 정보를 바탕으로 독립적으로 작업
```

---

## 6. 서브에이전트 vs 일반 도구

| | 일반 도구 | 서브에이전트 |
|---|---|---|
| 구현 | 단순 함수 | 에이전트 루프 |
| 내부 상태 | 없음 | 독립 state |
| 복잡도 | 단순 | 복잡한 멀티스텝 |
| 과정 가시성 | 메인 context에 노출 | 숨겨짐 |
| 실행 시간 | 밀리초 | 수 초~분 |
| 비용 | 도구 실행 비용만 | 추가 API 호출 비용 |

---

## 7. 실제 사용 사례

### Claude Code의 서브에이전트

Claude Code에서 `Agent` 도구를 사용할 때:
```
/agent subagent_type="Explore" ...
```

내부적으로 격리된 별도 에이전트가 탐색 작업을 수행하고,
메인 에이전트에게 요약만 반환한다.

### bomini에서의 사용 예시

```
user: "이 레포의 모든 코틀린 파일을 검토해서 
       코드 스타일 문제를 찾아줘"

main agent: spawn_sub_agent(
    task="src/ 디렉터리의 모든 .kt 파일을 검토하여 
          ktlint 스타일 가이드 위반을 찾고 목록으로 반환",
    tools=["list_dir", "read_file", "grep", "run_bash"]
)

sub_agent (내부 작업, 30턴):
  list_dir("src/")
  read_file("src/A.kt")
  read_file("src/B.kt")
  ...
  → "스타일 위반 12개: [상세 목록]"

main agent: 결과를 받아 사용자에게 전달
```

---

## 8. 서브에이전트 오케스트레이션

서브에이전트를 병렬로 실행하면 전체 처리 시간을 줄일 수 있다:

```kotlin
// 여러 서브에이전트 병렬 실행
suspend fun runParallelSubAgents(tasks: List<String>): List<String> {
    return coroutineScope {
        tasks.map { task ->
            async {
                val subState = mutableListOf(Message.user(task))
                runAgentLoop(subState, client, tools).finalText ?: ""
            }
        }.awaitAll()
    }
}
```

이것이 **에이전트 팀(Agent Team)**으로 발전한다 (다음 문서 참고).

---

## References

- [Anthropic Multi-Agent Architecture](https://docs.anthropic.com/en/docs/build-with-claude/build-with-claude-ios/multi-agent)
- [Building Effective Agents (Anthropic Blog, 2024)](https://www.anthropic.com/research/building-effective-agents)
- [Claude Code Agent Tool](https://docs.anthropic.com/en/docs/claude-code/sub-agents)
- [LangGraph — Multi-Agent Orchestration Framework](https://langchain-ai.github.io/langgraph/)
