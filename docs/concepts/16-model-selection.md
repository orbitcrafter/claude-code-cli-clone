# 모델 선택과 라우팅 (Model Selection & Routing)

> **한 줄 요약**: API 호출의 `model` 문자열을 바꾸는 것.
> `/model` 명령이나 자동 라우팅이나 결국 동일한 한 가지다.

---

## 1. 모델 선택의 본질

```kotlin
// 모델 선택의 전부
client.createMessage(
    messages = state,
    tools = tools,
    model = "claude-sonnet-4-6"   // ← 이 문자열 하나를 바꾸는 것
)
```

Claude Code의 `/model opus`, `/model sonnet` 명령은
다음 API 호출의 `model` 파라미터를 바꾸는 것이다. 그 이상도 이하도 아니다.

---

## 2. 모델 목록

```kotlin
enum class ClaudeModel(
    val id: String,
    val displayName: String,
    val contextWindow: Int,
    val inputCostPerMTok: Double,   // $ per million tokens
    val outputCostPerMTok: Double
) {
    OPUS_4(
        id = "claude-opus-4-8",
        displayName = "Claude Opus 4",
        contextWindow = 200_000,
        inputCostPerMTok = 15.0,
        outputCostPerMTok = 75.0
    ),
    SONNET_4(
        id = "claude-sonnet-4-6",
        displayName = "Claude Sonnet 4.6",
        contextWindow = 200_000,
        inputCostPerMTok = 3.0,
        outputCostPerMTok = 15.0
    ),
    HAIKU_4(
        id = "claude-haiku-4-5-20251001",
        displayName = "Claude Haiku 4.5",
        contextWindow = 200_000,
        inputCostPerMTok = 0.8,
        outputCostPerMTok = 4.0
    );

    companion object {
        fun fromAlias(alias: String): ClaudeModel? = when (alias.lowercase()) {
            "opus", "opus4" -> OPUS_4
            "sonnet", "sonnet4" -> SONNET_4
            "haiku", "haiku4" -> HAIKU_4
            else -> entries.firstOrNull { it.id == alias }
        }
    }
}
```

---

## 3. 모델 비교

| | Opus 4 | Sonnet 4.6 | Haiku 4.5 |
|---|---|---|---|
| **강점** | 최고 추론, 복잡한 분석 | 균형 (코딩 최적) | 속도, 비용 |
| **약점** | 느림, 비쌈 | — | 복잡 추론 약함 |
| **적합한 작업** | 아키텍처 설계, 복잡한 버그 | 일반 코딩 | 파일 탐색, 간단한 수정 |
| **입력 비용** | $15/MTok | $3/MTok | $0.8/MTok |
| **출력 비용** | $75/MTok | $15/MTok | $4/MTok |
| **상대 비용** | 5x | 1x (기준) | 0.27x |

---

## 4. 사용자 선택: `/model` 명령 구현

```kotlin
class SessionState(
    var currentModel: ClaudeModel = ClaudeModel.SONNET_4,
    // ...
)

// 슬래시 커맨드 처리
fun handleSlashCommand(input: String, session: SessionState): String? {
    val parts = input.trim().split(" ")
    
    return when (parts[0]) {
        "/model" -> {
            if (parts.size < 2) {
                // 현재 모델 표시
                "현재 모델: ${session.currentModel.displayName} (${session.currentModel.id})"
            } else {
                val requested = parts[1]
                val model = ClaudeModel.fromAlias(requested)
                if (model != null) {
                    session.currentModel = model
                    "모델 변경: ${model.displayName}"
                } else {
                    "알 수 없는 모델: $requested\n" +
                    "사용 가능: opus, sonnet, haiku"
                }
            }
        }
        else -> null  // 다른 커맨드는 다른 곳에서 처리
    }
}

// 에이전트 루프에서
val response = client.createMessage(
    messages = state,
    tools = tools,
    model = session.currentModel.id   // 현재 선택된 모델 사용
)
```

---

## 5. 자동 라우팅 (Auto-Routing)

작업의 복잡도에 따라 모델을 자동으로 선택한다:

```kotlin
fun selectModelForTask(userMessage: String, tools: List<Tool>): ClaudeModel {
    return when {
        // 단순 조회, 파일 탐색 → Haiku (빠름, 저렴)
        isSimpleQuery(userMessage) -> ClaudeModel.HAIKU_4
        
        // 복잡한 아키텍처 결정, 긴 분석 → Opus (강력)
        isComplexTask(userMessage) -> ClaudeModel.OPUS_4
        
        // 일반 코딩 작업 → Sonnet (균형)
        else -> ClaudeModel.SONNET_4
    }
}

fun isSimpleQuery(message: String): Boolean {
    val simplePatterns = listOf(
        Regex("""(어떤|무슨|뭐가) 파일"""),
        Regex("""목록"""),
        Regex("""읽어줘"""),
        Regex("""간단한""")
    )
    return simplePatterns.any { it.containsMatchIn(message) } &&
           message.length < 100  // 짧은 메시지
}

fun isComplexTask(message: String): Boolean {
    val complexPatterns = listOf(
        Regex("""아키텍처"""),
        Regex("""설계해줘"""),
        Regex("""전체.*리팩토링"""),
        Regex("""(분석|검토)해서.*정리""")
    )
    return complexPatterns.any { it.containsMatchIn(message) }
}
```

### 라우팅 전략 비교

| 전략 | 장점 | 단점 |
|---|---|---|
| 항상 Opus | 최고 품질 | 비용 5x |
| 항상 Haiku | 최저 비용 | 복잡한 작업 품질 저하 |
| 사용자 선택 | 제어권 | 사용자가 판단해야 함 |
| 자동 라우팅 | 비용/품질 균형 | 라우팅 정확도 문제 |
| 단계별 라우팅 | 정교한 균형 | 복잡도 증가 |

---

## 6. 단계별 라우팅 (Tiered Routing)

실제 프로덕션에서 사용하는 패턴:

```kotlin
// 1단계: Haiku로 작업 분류
suspend fun classifyTask(userMessage: String): TaskComplexity {
    val classificationResponse = client.createMessage(
        messages = listOf(Message.user(
            """다음 요청의 복잡도를 판단해줘. 한 단어로만 답해:
               - SIMPLE: 파일 읽기, 검색, 간단한 조회
               - MEDIUM: 코드 수정, 단일 기능 구현
               - COMPLEX: 아키텍처 설계, 대규모 리팩토링, 복잡한 분석
               
               요청: "$userMessage"
               
               답 (SIMPLE/MEDIUM/COMPLEX):"""
        )),
        tools = emptyList(),
        model = ClaudeModel.HAIKU_4.id   // 저렴한 모델로 분류
    )
    
    return when (classificationResponse.textContent?.trim()?.uppercase()) {
        "SIMPLE" -> TaskComplexity.SIMPLE
        "COMPLEX" -> TaskComplexity.COMPLEX
        else -> TaskComplexity.MEDIUM
    }
}

// 2단계: 분류에 따라 실제 작업 모델 선택
suspend fun routeTask(userMessage: String): ClaudeModel {
    val complexity = classifyTask(userMessage)
    return when (complexity) {
        TaskComplexity.SIMPLE -> ClaudeModel.HAIKU_4
        TaskComplexity.MEDIUM -> ClaudeModel.SONNET_4
        TaskComplexity.COMPLEX -> ClaudeModel.OPUS_4
    }
}
```

---

## 7. 작업별 모델 고정

특정 작업에는 항상 특정 모델을 사용:

```kotlin
// 도구 실행마다 모델을 다르게 쓸 수 있다
// (에이전트 루프 자체는 한 모델, 서브에이전트는 다른 모델)

// 오케스트레이터: Sonnet (균형)
// 탐색 서브에이전트: Haiku (빠름)
// 분석 서브에이전트: Opus (강력)

suspend fun orchestrate(task: String, client: AnthropicClient): String {
    // 탐색은 Haiku로
    val structure = runSubAgent(
        agentSpec = EXPLORER_SPEC.copy(model = ClaudeModel.HAIKU_4.id),
        task = "프로젝트 구조 탐색",
        client = client
    )
    
    // 복잡한 분석은 Opus로
    val analysis = runSubAgent(
        agentSpec = ANALYZER_SPEC.copy(model = ClaudeModel.OPUS_4.id),
        task = "심층 코드 분석: $structure",
        client = client
    )
    
    return analysis
}
```

---

## 8. 모델 상태 UI

```
bomini> /model
현재 모델: Claude Sonnet 4.6 (claude-sonnet-4-6)
컨텍스트: 200,000 토큰
비용: $3.00 입력 / $15.00 출력 (per M tokens)

bomini> /model opus
모델 변경: Claude Opus 4
(다음 호출부터 적용)

bomini> /model haiku
모델 변경: Claude Haiku 4.5
```

---

## 9. 비용 예측

```kotlin
fun estimateCost(
    inputTokens: Int,
    outputTokens: Int,
    model: ClaudeModel
): Double {
    return (inputTokens / 1_000_000.0 * model.inputCostPerMTok) +
           (outputTokens / 1_000_000.0 * model.outputCostPerMTok)
}

// 세션 종료 시 비용 요약
fun printSessionCost(session: Session, model: ClaudeModel) {
    val totalInput = session.usage.totalInputTokens
    val totalOutput = session.usage.totalOutputTokens
    val cost = estimateCost(totalInput, totalOutput, model)
    
    println("""
        세션 비용 요약:
        - 입력 토큰: ${totalInput.formatWithCommas()}
        - 출력 토큰: ${totalOutput.formatWithCommas()}
        - 예상 비용: ${"%.4f".format(cost)} USD
        - 모델: ${model.displayName}
    """.trimIndent())
}
```

---

## References

- [Anthropic Claude Models Overview](https://docs.anthropic.com/en/docs/about-claude/models)
- [Claude Pricing](https://www.anthropic.com/pricing)
- [LLM Routing Strategies (Survey)](https://arxiv.org/abs/2401.13601)
- [RouteLLM: Learning to Route LLMs with Preference Data](https://arxiv.org/abs/2406.18665)
