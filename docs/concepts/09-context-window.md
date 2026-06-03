# 컨텍스트 윈도우 관리 (Context Window Management)

> **한 줄 요약**: 모델이 한 번에 읽을 수 있는 텍스트의 최대 크기.
> 이 한계가 에이전트 설계의 가장 현실적인 제약이다.

---

## 1. 컨텍스트 윈도우란

LLM은 무한한 기억을 갖지 않는다. 한 번의 API 호출에서 처리할 수 있는 텍스트의 양이 정해져 있고,
이를 **컨텍스트 윈도우(context window)**라고 한다.

단위는 **토큰(token)**이다.
토큰은 단어도 아니고 글자도 아닌, LLM의 내부 처리 단위다.

```
영어: 1 토큰 ≈ 4글자 ≈ 0.75 단어
한국어: 1 토큰 ≈ 1~2 글자 (영어보다 토큰 효율이 낮음)

"Hello World" → 2 토큰
"안녕하세요" → 4~5 토큰  
```

---

## 2. Claude 모델별 컨텍스트 윈도우

| 모델 | 입력 컨텍스트 | 출력 최대 |
|---|---|---|
| Claude Opus 4 | 200,000 토큰 | 32,000 토큰 |
| Claude Sonnet 4.6 | 200,000 토큰 | 64,000 토큰 |
| Claude Haiku 4.5 | 200,000 토큰 | 8,192 토큰 |

200K 토큰 ≈ 150,000 단어 ≈ 소설 1~2권 분량

이 숫자가 크게 느껴지지만, 에이전트가 파일을 여러 개 읽고 대화를 나누다 보면 금방 찬다.

---

## 3. 토큰 소비 패턴

에이전트 루프에서 토큰이 어디서 소비되는가:

```
[1회 API 호출의 입력 토큰 = 모든 것의 합]

system prompt          → 수백~수천 토큰 (룰 파일, 도구 스키마)
전체 대화 이력         → 누적될수록 증가
  - 각 user 메시지
  - 각 assistant 응답 (tool_use 포함)
  - 각 tool_result
읽은 파일 내용들       → 큰 파일 하나가 수천 토큰

[비용]
= input_tokens × 입력 단가 + output_tokens × 출력 단가
```

### 실제 예시 (Sonnet 4.6, $3/MTok input)

```
10회 대화 후 예상 누적 토큰:
- system prompt: ~2,000
- 각 대화 10쌍: ~5,000
- 읽은 파일 3개: ~6,000
합계: ~13,000 input tokens

비용: 13,000 / 1,000,000 × $3 = $0.039 (약 50원)

100회 대화 후:
- 누적 대화: ~50,000
- 파일들: ~20,000
합계: ~75,000 input tokens

비용: ~$0.225 (약 300원)
```

---

## 4. 토큰 추정

정확한 토큰 수는 tokenizer를 사용해야 한다.
Anthropic은 tiktoken 호환 tokenizer를 제공하지 않으므로, 근사치를 사용한다.

### 간단한 근사

```kotlin
fun estimateTokens(text: String): Int {
    // 영어: 4글자 = 1토큰, 한국어: 2글자 = 1토큰 (혼합)
    // 안전하게 글자수 / 3 + 버퍼
    return (text.length / 3.0 + 100).toInt()
}

fun estimateMessageTokens(messages: List<Message>): Int {
    return messages.sumOf { msg ->
        msg.content.sumOf { block ->
            when (block) {
                is ContentBlock.Text -> estimateTokens(block.text)
                is ContentBlock.ToolUse -> estimateTokens(block.input.toString()) + 50
                is ContentBlock.ToolResult -> estimateTokens(block.content) + 10
            }
        } + 4  // 메시지 오버헤드
    }
}
```

### API 응답에서 실제 토큰 수 확인

```kotlin
// 모든 응답에 usage가 포함됨
val response = client.createMessage(...)
println("Input: ${response.usage.inputTokens}, Output: ${response.usage.outputTokens}")
```

---

## 5. 컨텍스트 한계 감지

```kotlin
const val CONTEXT_WINDOW_SIZE = 200_000
const val WARNING_THRESHOLD = 0.7    // 70%: 경고
const val CRITICAL_THRESHOLD = 0.85  // 85%: compaction 트리거

fun checkContextUsage(inputTokens: Int): ContextStatus {
    val usage = inputTokens.toDouble() / CONTEXT_WINDOW_SIZE
    return when {
        usage > CRITICAL_THRESHOLD -> ContextStatus.CRITICAL
        usage > WARNING_THRESHOLD -> ContextStatus.WARNING
        else -> ContextStatus.OK
    }
}

enum class ContextStatus { OK, WARNING, CRITICAL }
```

---

## 6. 컨텍스트 최적화 전략

### 전략 1: 읽기 도구에 크기 제한

```kotlin
// 대용량 파일은 필요한 부분만 읽기
read_file(path="huge_log.txt", offset=5000, limit=100)

// 결과 크기 제한 (이미 구현함)
val output = process.inputStream.readNBytes(MAX_OUTPUT_BYTES)
```

### 전략 2: 도구 스키마 최적화

도구 스키마도 매 호출마다 전송된다. description이 너무 길면 낭비다:

```kotlin
// 나쁜 예: 도구 description이 500 토큰
description = """
This tool reads files from the filesystem. It can handle various file types
including text files, source code, configuration files, and more. You should
use this tool whenever you need to examine the contents of a file...
"""

// 좋은 예: 간결하게
description = "Read file contents. Use to examine code, config, and text files."
```

### 전략 3: 오래된 tool_result 압축

긴 도구 결과는 "요약본"으로 교체:

```kotlin
// 원본: 파일 내용 3000 토큰
// 요약: "파일을 읽었음. 주요 내용: 함수 5개, 클래스 2개"

fun compressOldToolResults(messages: List<Message>, keepLast: Int = 5): List<Message> {
    // 최근 keepLast개 제외한 tool_result를 요약으로 대체
    return messages.mapIndexed { i, msg ->
        if (i < messages.size - keepLast && msg.hasLargeToolResult()) {
            msg.compressToolResults()
        } else msg
    }
}
```

### 전략 4: 컨텍스트 선택

모든 파일을 읽는 대신 관련있는 파일만 선택:

```kotlin
// 나쁜 패턴: 코드베이스 전체를 읽음
// → 수만 토큰 낭비

// 좋은 패턴: grep → 관련 파일 특정 → 그것만 읽음
grep("UserService")
→ src/service/UserService.kt:12
→ read_file("src/service/UserService.kt")
```

---

## 7. 컨텍스트 윈도우와 메모리의 차이

자주 혼동하는 개념:

| | 컨텍스트 윈도우 | 외부 메모리 |
|---|---|---|
| 위치 | 모델 내부 (in-context) | 파일/DB (out-of-context) |
| 접근 방식 | 직접 (모델이 읽음) | 도구 호출 (read_file 등) |
| 한계 | 200K 토큰 | 무제한 |
| 속도 | 즉각 | 도구 호출 필요 |
| 비용 | 토큰 단가 | 저장소 비용 |

에이전트가 기억을 유지하는 두 가지 방법:
1. **In-context**: 대화 이력을 모두 state에 유지 → 용량 한계
2. **Out-of-context**: 파일/DB에 저장, 필요할 때 읽기 → 무한하지만 능동적 호출 필요

---

## 8. 200K가 한계인 이유 (기술적 배경)

Transformer 모델의 self-attention은 O(n²) 복잡도를 가진다:
- n = 1,000 토큰: 1M 연산
- n = 10,000 토큰: 100M 연산  
- n = 200,000 토큰: 40B 연산

200K 토큰이 현재 실용적 상한에 가깝다.
Sliding window attention, sparse attention 등이 이 문제를 개선하고 있다.

---

## References

- [Anthropic Claude Models — Context Windows](https://docs.anthropic.com/en/docs/about-claude/models)
- [Anthropic Token Counting API](https://docs.anthropic.com/en/api/messages-count-tokens)
- [Attention Is All You Need (Transformer 원논문, 2017)](https://arxiv.org/abs/1706.03762)
- [Efficient Transformers: A Survey](https://arxiv.org/abs/2009.06732)
- [tiktoken (OpenAI tokenizer, 참고)](https://github.com/openai/tiktoken)
