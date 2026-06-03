# 컴팩트 (Compaction / Context Compression)

> **한 줄 요약**: 대화가 길어져 컨텍스트 윈도우가 가득 차면,
> 모델을 한 번 더 호출해서 긴 대화를 요약으로 압축한다.
> **정보 손실은 피할 수 없다. 그것이 핵심 학습 포인트다.**

---

## 1. 왜 Compaction이 필요한가

에이전트 루프가 계속 돌면 state가 점점 커진다:

```
Turn 1: [user(50토큰)]
Turn 5: [user(50) + assistant(200) + tool×3(500) + user(50) + ...] → ~2,000토큰
Turn 20: → ~10,000토큰
Turn 100: → ~60,000토큰
Turn 500: → 200K 토큰 한계 도달 → 더 이상 호출 불가
```

해결 방법:
1. **세션 종료**: 그냥 포기하고 새 세션 시작
2. **오래된 메시지 삭제**: 단순하지만 완전 손실
3. **Compaction**: 오래된 메시지를 요약으로 교체 → 부분 손실

Claude Code는 Compaction 방식을 사용한다.

---

## 2. Compaction의 동작 원리

```
[현재 state: 너무 긺]

─────────────────────────────────────────────
user: "파일 구조 만들어줘"                    ← 압축 대상 (오래됨)
assistant: [tool_use: list_dir]              ← 압축 대상
user: [tool_result: "README.md\nsrc/..."]   ← 압축 대상
assistant: [tool_use: write_file "Main.kt"] ← 압축 대상
user: [tool_result: "파일 생성 완료"]        ← 압축 대상
assistant: "Main.kt를 생성했습니다"          ← 압축 대상
─────────────────────────────────────────────
user: "이제 Agent.kt도 만들어줘"             ← 보존 (최근)
assistant: [tool_use: write_file "Agent.kt"] ← 보존
user: [tool_result: "생성 완료"]             ← 보존
─────────────────────────────────────────────

     ↓ Compaction

─────────────────────────────────────────────
system: [요약] "이전에 다음 작업을 수행함:   ← 압축 결과
  - 디렉터리 구조 탐색
  - Main.kt 생성 (fun main() {} 포함)
  현재 작업 디렉터리: /Users/dev/project"
─────────────────────────────────────────────
user: "이제 Agent.kt도 만들어줘"             ← 보존
assistant: [tool_use: write_file "Agent.kt"] ← 보존
user: [tool_result: "생성 완료"]             ← 보존
─────────────────────────────────────────────
```

오래된 메시지들이 **하나의 요약 메시지**로 교체된다.

---

## 3. Compaction 알고리즘

### 언제 트리거하는가

```kotlin
const val COMPACTION_THRESHOLD = 0.85    // 85%면 compaction 시작
const val KEEP_RECENT_MESSAGES = 10      // 최근 N개는 무조건 보존

fun shouldCompact(inputTokens: Int, contextWindowSize: Int): Boolean {
    return inputTokens.toDouble() / contextWindowSize > COMPACTION_THRESHOLD
}
```

### 어떻게 압축하는가

```kotlin
suspend fun compact(
    state: List<Message>,
    client: AnthropicClient,
    model: String
): List<Message> {
    // 1. 보존할 최근 메시지 분리
    val recentMessages = state.takeLast(KEEP_RECENT_MESSAGES)
    val oldMessages = state.dropLast(KEEP_RECENT_MESSAGES)
    
    if (oldMessages.isEmpty()) return state  // 압축할 내용 없음
    
    // 2. 오래된 메시지를 요약 요청
    val summaryRequest = listOf(
        Message(
            role = "user",
            content = listOf(ContentBlock.Text(
                buildString {
                    appendLine("다음 대화 이력을 간결하게 요약해줘.")
                    appendLine("다음을 포함할 것:")
                    appendLine("- 수행한 주요 작업들")
                    appendLine("- 생성/수정된 파일 목록과 내용")
                    appendLine("- 현재 상태와 context")
                    appendLine("- 아직 해결되지 않은 사항")
                    appendLine()
                    appendLine("=== 대화 이력 ===")
                    oldMessages.forEach { msg ->
                        appendLine("[${msg.role}]: ${msg.contentSummary()}")
                    }
                }
            ))
        )
    )
    
    // 3. 모델로 요약 생성 (Haiku 사용 — 저렴)
    val summaryResponse = client.createMessage(
        messages = summaryRequest,
        tools = emptyList(),
        model = ClaudeModel.HAIKU_4.id
    )
    
    val summaryText = summaryResponse.textContent
        ?: return state  // 요약 실패 시 그대로 반환
    
    // 4. 요약 메시지 + 최근 메시지로 새 state 구성
    val summaryMessage = Message(
        role = "user",
        content = listOf(ContentBlock.Text(
            "[이전 대화 요약]\n$summaryText"
        ))
    )
    
    return listOf(summaryMessage) + recentMessages
}
```

---

## 4. 정보 손실의 실체 (핵심 학습 포인트)

Compaction 후 "방금 전에 뭐 했지?"를 물어보면:

**Before compaction:**
```
user: "Main.kt에서 readFile 함수의 13번째 줄에 있는 val x = 1을 val x = 2로 바꿨어?"
agent: "네, readFile 함수의 13번째 줄, 구체적으로 다음 코드를..."
```

**After compaction:**
```
user: "Main.kt에서 readFile 함수의 13번째 줄에 있는 val x = 1을 val x = 2로 바꿨어?"
agent: "이전 대화 요약에 따르면 Main.kt를 수정했습니다만, 
        정확한 줄 번호나 변경 내용의 세부사항은 요약에 포함되지 않았습니다.
        파일을 다시 읽어서 확인해드릴까요?"
```

이것이 "컨텍스트 압축의 정보 손실"이다:
- 대화의 **흐름과 결과**는 요약에 남는다
- 세부 내용(정확한 줄 번호, 변수명, 구체적 내용)은 사라진다
- 모델은 사라진 정보를 "모른다"고 정직하게 말하거나, 잘못 기억하기도 한다

---

## 5. Compaction 트레이드오프

| | 방법 | 장점 | 단점 |
|---|---|---|---|
| 삭제 | 오래된 메시지 버림 | 구현 단순 | 완전 손실 |
| 요약 | 모델로 요약 생성 | 흐름 유지 | 세부 손실 + 비용 |
| 슬라이딩 윈도우 | 최근 N개만 유지 | 최신 내용 완전 보존 | 오래된 내용 완전 손실 |
| 계층 요약 | 여러 단계 요약 | 정보 손실 최소화 | 복잡도 높음 |

Claude Code는 기본적으로 **요약(summarization)** 방식을 사용한다.

---

## 6. 에이전트 루프에 Compaction 통합

```kotlin
suspend fun agentLoop(
    state: MutableList<Message>,
    client: AnthropicClient,
    tools: List<Tool>
) {
    while (true) {
        // Compaction 체크
        val estimatedTokens = estimateMessageTokens(state)
        if (shouldCompact(estimatedTokens, CONTEXT_WINDOW_SIZE)) {
            println("[컨텍스트 압축 중... ${estimatedTokens}토큰]")
            val compacted = compact(state, client, currentModel)
            state.clear()
            state.addAll(compacted)
            println("[압축 완료: ${estimateMessageTokens(state)}토큰]")
        }
        
        val response = client.createMessage(state, tools)
        state.add(response.toMessage())
        
        val toolUses = response.toolUses
        if (toolUses.isEmpty()) break
        
        val results = toolUses.map { runTool(it) }
        state.add(Message.toolResults(results))
    }
}
```

---

## 7. Compaction 로그

학습 목적으로 compaction 전후 상태를 로깅:

```kotlin
fun logCompaction(before: List<Message>, after: List<Message>) {
    println("""
        [COMPACTION]
        Before: ${before.size}개 메시지, ~${estimateMessageTokens(before)}토큰
        After:  ${after.size}개 메시지, ~${estimateMessageTokens(after)}토큰
        절감:   ~${estimateMessageTokens(before) - estimateMessageTokens(after)}토큰
    """.trimIndent())
}
```

---

## 8. Claude Code의 실제 Compaction

Claude Code는 `/compact` 슬래시 커맨드로 수동 compaction을 지원하며,
자동으로도 context가 채워지면 실행한다.

압축 후 UI에 표시:
```
> [Context was compacted: 47 messages → 1 summary (saved 85% of context)]
```

---

## References

- [Anthropic Claude Code Memory Documentation](https://docs.anthropic.com/en/docs/claude-code/memory)
- [LangChain Memory Types (유사 개념)](https://python.langchain.com/docs/how_to/memory_summary/)
- [Summarization with LLMs (Techniques)](https://arxiv.org/abs/2310.01848)
- [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172)
