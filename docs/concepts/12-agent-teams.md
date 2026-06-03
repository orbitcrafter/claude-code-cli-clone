# 에이전트 팀 (Agent Teams / Multi-Agent Orchestration)

> **한 줄 요약**: 여러 서브에이전트가 각자의 전문 영역에서 병렬/순차로 작업하고,
> 메인 에이전트(오케스트레이터)가 결과를 종합하는 구조.

---

## 1. 에이전트 팀의 정의

서브에이전트가 하나면 "위임(delegation)"이고,
여러 개면 "팀(team)" 또는 "오케스트레이션(orchestration)"이다.

```
[오케스트레이터 (Main Agent)]
        │
   ┌────┴────┐────────────────────┐
   ▼         ▼                    ▼
[서브A]   [서브B]              [서브C]
(파일탐색) (코드분석)          (테스트실행)
   │         │                    │
   └────┬────┘────────────────────┘
        ▼
   [결과 종합 → 최종 답변]
```

각 서브에이전트는:
- 자신만의 격리된 state를 가짐
- 자신만의 전문 도구 세트를 가짐
- 자신만의 system prompt (전문성)를 가짐
- 병렬 또는 순차로 실행 가능

---

## 2. 오케스트레이터의 역할

오케스트레이터는 다음을 담당한다:

1. **작업 분해**: 큰 작업을 서브에이전트가 처리할 수 있는 단위로 나눔
2. **에이전트 선택**: 각 작업에 맞는 전문 에이전트 선택
3. **순서 결정**: 의존성이 있는 작업은 순차, 없는 것은 병렬
4. **결과 종합**: 여러 에이전트의 결과를 합쳐서 최종 답변 생성
5. **에러 처리**: 서브에이전트 실패 시 재시도 또는 대안 선택

---

## 3. 구현 패턴

### 패턴 1: 정적 팀 (역할 고정)

```kotlin
// 각 전문 에이전트 정의
data class AgentSpec(
    val name: String,
    val systemPrompt: String,
    val tools: List<Tool>,
    val model: String
)

val EXPLORER_AGENT = AgentSpec(
    name = "Explorer",
    systemPrompt = "You are a code exploration specialist. Find files and understand structure.",
    tools = listOf(LIST_DIR_TOOL, READ_FILE_TOOL, GREP_TOOL),
    model = ClaudeModel.HAIKU_4.id  // 빠르고 저렴
)

val ANALYZER_AGENT = AgentSpec(
    name = "Analyzer",
    systemPrompt = "You are a code analysis specialist. Analyze code quality and patterns.",
    tools = listOf(READ_FILE_TOOL, GREP_TOOL, RUN_BASH_TOOL),
    model = ClaudeModel.SONNET_4.id  // 더 강한 분석력
)

val EXECUTOR_AGENT = AgentSpec(
    name = "Executor",
    systemPrompt = "You are a code execution specialist. Run builds and tests.",
    tools = listOf(RUN_BASH_TOOL, READ_FILE_TOOL),
    model = ClaudeModel.SONNET_4.id
)

// 오케스트레이터
suspend fun orchestrate(task: String): String {
    // 1. 탐색 (빠른 에이전트로)
    val structure = runSubAgent(EXPLORER_AGENT, "프로젝트 구조 파악: $task")
    
    // 2. 분석 + 실행 (병렬)
    val (analysis, testResult) = coroutineScope {
        val analysisDeferred = async {
            runSubAgent(ANALYZER_AGENT, "코드 분석: $structure")
        }
        val executionDeferred = async {
            runSubAgent(EXECUTOR_AGENT, "빌드 및 테스트 실행")
        }
        Pair(analysisDeferred.await(), executionDeferred.await())
    }
    
    // 3. 메인 에이전트가 결과 종합
    return synthesize(structure, analysis, testResult)
}
```

### 패턴 2: 동적 팀 (LLM이 팀 구성 결정)

```kotlin
// 오케스트레이터가 스스로 어떤 에이전트를 쓸지 결정
val ORCHESTRATOR_TOOLS = listOf(
    // 서브에이전트를 호출하는 도구들
    Tool("explore_codebase", "Use Explore specialist agent to find and understand code"),
    Tool("analyze_code", "Use Analyzer specialist agent to review code quality"),
    Tool("run_tests", "Use Executor agent to run tests and builds"),
    Tool("write_code", "Use Writer agent to create or modify code")
)

// 오케스트레이터는 이 도구들을 "고수준 도구"로 사용
// 내부적으로 각 도구가 전문 서브에이전트를 실행
```

---

## 4. 에이전트 팀 아키텍처 패턴

### 4-1. Hierarchical (계층형)

```
오케스트레이터
    ├── 매니저 A
    │     ├── 워커 A1
    │     └── 워커 A2
    └── 매니저 B
          ├── 워커 B1
          └── 워커 B2
```

복잡한 작업에서 계층 구조로 분해. bomini에서는 일반적으로 2계층으로 충분.

### 4-2. Pipeline (파이프라인)

```
에이전트1 → 에이전트2 → 에이전트3 → 결과
 (탐색)      (분석)      (수정)
```

순차 의존성이 있는 작업에 적합.

### 4-3. Parallel (병렬)

```
에이전트1 ─┐
에이전트2 ─┤→ 결과 종합
에이전트3 ─┘
```

독립적인 작업들을 동시에 처리.

---

## 5. 실제 구현: coroutineScope

```kotlin
suspend fun runAgentTeam(
    task: String,
    client: AnthropicClient
): String {
    // 병렬 실행
    return coroutineScope {
        val tasks = decomposeTask(task)  // 작업 분해

        // 의존성 없는 작업들 병렬 실행
        val independentResults = tasks
            .filter { !it.hasDependencies }
            .map { subTask ->
                async {
                    SubTask(
                        name = subTask.name,
                        result = runSubAgent(subTask.spec, subTask.description, client)
                    )
                }
            }
            .awaitAll()

        // 의존성 있는 작업들 순차 실행
        val dependentResults = tasks
            .filter { it.hasDependencies }
            .map { subTask ->
                val prerequisites = independentResults
                    .filter { it.name in subTask.dependencies }
                
                SubTask(
                    name = subTask.name,
                    result = runSubAgent(
                        subTask.spec,
                        "${subTask.description}\n\n이전 작업 결과:\n${prerequisites.joinToString("\n")}",
                        client
                    )
                )
            }

        // 전체 결과 종합
        val allResults = independentResults + dependentResults
        synthesizeResults(task, allResults, client)
    }
}
```

---

## 6. 에이전트 팀의 비용 계산

에이전트 팀은 강력하지만 비용이 선형으로 증가한다:

```
단일 에이전트: 1 API 호출 사이클
서브에이전트 1개 추가: +N API 호출 (서브에이전트의 턴 수)
에이전트 팀 3개: +3N API 호출

예:
- 메인 에이전트: 5턴 × 10K 토큰 = 50K 토큰
- 서브에이전트 3개 × 20턴 × 5K 토큰 = 300K 토큰
- 총: 350K 토큰

Sonnet 4.6 기준: 350K × $3/MTok ≈ $1.05 (약 1,500원)
```

비용 통제 전략:
1. 서브에이전트에 저렴한 모델 사용 (Haiku)
2. 서브에이전트의 최대 턴 수 제한
3. 필요한 작업만 위임 (모든 것을 서브에이전트로 하지 않음)

---

## 7. 에러 처리와 결과 검증

```kotlin
data class AgentResult(
    val agentName: String,
    val success: Boolean,
    val result: String,
    val error: String? = null
)

suspend fun runSubAgentSafe(
    spec: AgentSpec,
    task: String,
    client: AnthropicClient
): AgentResult {
    return try {
        val result = runSubAgent(spec, task, client)
        AgentResult(spec.name, success = true, result = result)
    } catch (e: Exception) {
        AgentResult(
            spec.name,
            success = false,
            result = "",
            error = "서브에이전트 실패: ${e.message}"
        )
    }
}

// 오케스트레이터에서
val results = runParallel(subTasks)
val failures = results.filter { !it.success }
if (failures.isNotEmpty()) {
    // 실패한 작업 재시도 또는 스킵
    println("경고: ${failures.size}개 서브에이전트 실패")
}
```

---

## 8. Claude Code의 에이전트 팀

Claude Code에서는 다음 에이전트 타입들이 있다:

| 에이전트 | 역할 |
|---|---|
| `Explore` | 파일 탐색 및 검색 전문 |
| `general-purpose` | 범용 작업 |
| `Plan` | 구현 계획 수립 |
| `code-reviewer` | 코드 리뷰 전문 |

```kotlin
// Claude Code 내부 개념
Agent(subagent_type="Explore", prompt="...")
  // → 격리된 Explore 에이전트 실행
  // → 탐색에 특화된 도구만 사용
  // → 결과 요약만 메인 context에 추가
```

---

## References

- [Anthropic Building Effective Agents (Dec 2024)](https://www.anthropic.com/research/building-effective-agents)
- [LangGraph Multi-Agent Architecture](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation (Microsoft)](https://arxiv.org/abs/2308.08155)
- [CrewAI — Multi-Agent Frameworks](https://github.com/crewAIInc/crewAI)
- [Kotlin Coroutines — async/await](https://kotlinlang.org/docs/coroutines-basics.html)
