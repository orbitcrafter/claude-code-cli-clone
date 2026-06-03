# Anthropic API 클라이언트 (모델 HTTP 클라이언트)

> **한 줄 요약**: 우리 앱은 Anthropic의 REST API를 호출하는 HTTP 클라이언트일 뿐이다.
> SDK가 감춰주는 것을 직접 봄으로써 "앱 = API 클라이언트"를 체감한다.

---

## 1. API의 전체 그림

```
[bomini app]
    │
    │  POST https://api.anthropic.com/v1/messages
    │  Headers:
    │    x-api-key: sk-ant-...
    │    anthropic-version: 2023-06-01
    │    content-type: application/json
    │
    ▼
[Anthropic Claude API]
    │
    │  Response: JSON (또는 SSE stream)
    ▼
[bomini app이 응답 파싱 → state에 주입]
```

이것이 전부다. "모델 호출"의 실체는 HTTPS POST 요청 한 번이다.

---

## 2. 엔드포인트와 필수 헤더

### 엔드포인트

```
POST https://api.anthropic.com/v1/messages
```

### 필수 헤더

| 헤더 | 값 | 설명 |
|---|---|---|
| `x-api-key` | `sk-ant-api03-...` | Anthropic 콘솔에서 발급받은 API 키 |
| `anthropic-version` | `2023-06-01` | API 버전 핀닝. 변경 시 Breaking Change 방지 |
| `content-type` | `application/json` | 요청 바디 형식 |

### 선택 헤더

| 헤더 | 설명 |
|---|---|
| `anthropic-beta` | 베타 기능 활성화 (예: `structured-outputs-2025-11-13`) |

---

## 3. 요청 바디 구조

```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 8192,
  "system": "You are a helpful coding assistant.",
  "messages": [
    {
      "role": "user",
      "content": "현재 디렉터리의 파일을 나열해줘"
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "tool_use",
          "id": "toolu_01A09q90qw90lq917835lq9",
          "name": "list_dir",
          "input": { "path": "." }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_01A09q90qw90lq917835lq9",
          "content": "README.md\nsrc/\nbuild.gradle.kts"
        }
      ]
    }
  ],
  "tools": [
    {
      "name": "list_dir",
      "description": "Lists files and directories at the given path",
      "input_schema": {
        "type": "object",
        "properties": {
          "path": { "type": "string", "description": "Directory path to list" }
        },
        "required": ["path"]
      }
    }
  ]
}
```

### 핵심 필드 설명

| 필드 | 타입 | 설명 |
|---|---|---|
| `model` | string | 사용할 모델 ID |
| `max_tokens` | int | 응답 최대 토큰 수 (필수) |
| `system` | string | 시스템 프롬프트 (룰/BOMINI.md 내용이 들어감) |
| `messages` | array | 전체 대화 이력 (= state) |
| `tools` | array | 사용 가능한 도구 목록 |
| `stream` | bool | `true`로 설정 시 SSE 스트리밍 |
| `temperature` | float | 0.0~1.0, 기본값 1.0 |

---

## 4. 응답 바디 구조

### 비스트리밍 응답

```json
{
  "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
  "type": "message",
  "role": "assistant",
  "model": "claude-sonnet-4-6",
  "content": [
    {
      "type": "text",
      "text": "파일 목록을 가져오겠습니다."
    },
    {
      "type": "tool_use",
      "id": "toolu_01A09q90qw90lq917835lq9",
      "name": "list_dir",
      "input": { "path": "." }
    }
  ],
  "stop_reason": "tool_use",
  "usage": {
    "input_tokens": 1024,
    "output_tokens": 47
  }
}
```

### stop_reason 값

| stop_reason | 의미 |
|---|---|
| `tool_use` | 도구를 호출했으므로 루프 계속 |
| `end_turn` | 자연스러운 종료 (루프 break) |
| `max_tokens` | 최대 토큰 도달 |
| `stop_sequence` | 지정한 stop sequence 만남 |

---

## 5. 모델 ID 목록 (현재 기준)

```kotlin
enum class ClaudeModel(val id: String) {
    OPUS_4("claude-opus-4-8"),
    SONNET_4("claude-sonnet-4-6"),
    HAIKU_4("claude-haiku-4-5-20251001"),
}
```

| 모델 | 특성 | 적합한 용도 |
|---|---|---|
| Opus 4.8 | 가장 강력, 느리고 비쌈 | 복잡한 추론, 장문 분석 |
| Sonnet 4.6 | 균형, 빠름 | 일반 코딩 작업 |
| Haiku 4.5 | 가장 빠르고 저렴 | 단순 조회, 대량 처리 |

---

## 6. Kotlin 구현 (Ktor Client)

### 의존성 (build.gradle.kts)

```kotlin
dependencies {
    // Ktor HTTP Client
    implementation("io.ktor:ktor-client-core:2.3.7")
    implementation("io.ktor:ktor-client-cio:2.3.7")          // CIO 엔진 (코루틴 기반)
    implementation("io.ktor:ktor-client-content-negotiation:2.3.7")
    implementation("io.ktor:ktor-serialization-kotlinx-json:2.3.7")
    implementation("io.ktor:ktor-client-logging:2.3.7")

    // 직렬화
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
}
```

### AnthropicClient 구현

```kotlin
class AnthropicClient(
    private val apiKey: String = System.getenv("ANTHROPIC_API_KEY")
        ?: error("ANTHROPIC_API_KEY not set")
) {
    private val httpClient = HttpClient(CIO) {
        install(ContentNegotiation) {
            json(Json { ignoreUnknownKeys = true })
        }
        install(HttpTimeout) {
            requestTimeoutMillis = 120_000   // 2분
            connectTimeoutMillis = 10_000
        }
    }

    suspend fun createMessage(
        messages: List<Message>,
        tools: List<Tool>,
        model: String = ClaudeModel.SONNET_4.id,
        system: String? = null,
        maxTokens: Int = 8192
    ): MessageResponse {
        return httpClient.post("https://api.anthropic.com/v1/messages") {
            header("x-api-key", apiKey)
            header("anthropic-version", "2023-06-01")
            contentType(ContentType.Application.Json)
            setBody(
                MessageRequest(
                    model = model,
                    messages = messages,
                    tools = tools,
                    system = system,
                    maxTokens = maxTokens
                )
            )
        }.body<MessageResponse>()
    }
}
```

---

## 7. 인증 처리

API 키는 절대 코드에 하드코딩하지 않는다.

```kotlin
// 올바른 방법: 환경변수에서 읽기
val apiKey = System.getenv("ANTHROPIC_API_KEY")
    ?: throw IllegalStateException("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다")

// 또는 ~.bomini/config 파일에서 읽기 (Phase 6에서 구현)
val apiKey = loadFromConfig("~/.bomini/config")
```

```bash
# 터미널에서 설정
export ANTHROPIC_API_KEY="sk-ant-api03-..."

# 또는 ~/.zshrc에 추가 (영구 설정)
echo 'export ANTHROPIC_API_KEY="sk-ant-api03-..."' >> ~/.zshrc
```

---

## 8. 에러 처리와 재시도

### HTTP 상태 코드

| 코드 | 의미 | 처리 방법 |
|---|---|---|
| `400` | 잘못된 요청 | 요청 파라미터 수정 필요 |
| `401` | 인증 실패 | API 키 확인 |
| `403` | 권한 없음 | API 키 권한 확인 |
| `429` | Rate limit 초과 | Exponential backoff로 재시도 |
| `500`, `529` | 서버 오류 | 잠시 후 재시도 |

### Exponential Backoff 구현

```kotlin
suspend fun <T> withRetry(
    maxAttempts: Int = 3,
    block: suspend () -> T
): T {
    repeat(maxAttempts) { attempt ->
        try {
            return block()
        } catch (e: ClientRequestException) {
            if (e.response.status.value == 429) {
                // Rate limit: 지수적 대기
                val waitMs = (2.0.pow(attempt) * 1000).toLong()
                delay(waitMs)
            } else throw e
        }
    }
    throw IllegalStateException("Max retry attempts exceeded")
}
```

---

## 9. 토큰 사용량 추적

모든 응답에는 `usage` 필드가 포함된다:

```kotlin
data class Usage(
    val inputTokens: Int,     // 입력(context) 토큰 수
    val outputTokens: Int     // 출력(생성) 토큰 수
)

// 비용 계산 예 (Sonnet 4.6 기준, USD)
val inputCost = usage.inputTokens / 1_000_000.0 * 3.0    // $3/MTok
val outputCost = usage.outputTokens / 1_000_000.0 * 15.0  // $15/MTok
val totalCost = inputCost + outputCost
```

---

## 10. SDK를 직접 구현하는 이유

공식 Anthropic Python SDK나 TypeScript SDK는 내부적으로 이 HTTP 호출을 감싼다.
Kotlin SDK는 공식적으로 존재하지 않으므로 직접 구현이 필요하고, 이것이 오히려 학습에 이점이 된다:

1. **"앱 = API 클라이언트"**라는 사실이 코드에서 직접 보인다
2. 요청/응답 포맷을 완전히 이해하게 된다
3. 스트리밍, 재시도, 타임아웃 등 제어권이 우리 코드에 있다
4. 특정 SDK에 종속되지 않는다

---

## References

- [Anthropic Messages API Reference](https://docs.anthropic.com/en/api/messages)
- [Anthropic API Authentication](https://docs.anthropic.com/en/api/getting-started)
- [Ktor HTTP Client Documentation](https://ktor.io/docs/client-create-and-configure.html)
- [kotlinx.serialization Documentation](https://kotlinlang.org/docs/serialization.html)
- [Anthropic Model Overview](https://docs.anthropic.com/en/docs/about-claude/models)
- [Anthropic Error Codes](https://docs.anthropic.com/en/api/errors)
