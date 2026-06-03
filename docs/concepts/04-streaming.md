# 스트리밍 응답 처리 (Streaming Response)

> **한 줄 요약**: 모델이 토큰을 생성하는 즉시 화면에 출력하는 것.
> 기술적으로는 Server-Sent Events(SSE) 위에서 동작한다.

---

## 1. 왜 스트리밍인가?

비스트리밍 방식:
```
요청 → [서버가 전체 생성] → 응답 (수 초 대기) → 화면에 한꺼번에 출력
```

스트리밍 방식:
```
요청 → [서버가 토큰 단위로 전송] → 각 토큰 즉시 출력 (체감 속도 훨씬 빠름)
         token1→ token2→ token3→ ...
```

Claude Code가 실시간으로 코드를 "타이핑"하는 것처럼 보이는 것이 바로 스트리밍이다.

---

## 2. Server-Sent Events (SSE) 기초

SSE는 서버가 클라이언트에게 단방향으로 이벤트를 푸시하는 HTTP 기반 프로토콜이다.

### HTTP 응답 헤더

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

### SSE 이벤트 포맷

```
event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"안녕"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"하세요"}}

event: message_stop
data: {"type":"message_stop"}
```

각 이벤트는:
- `event:` 줄 — 이벤트 타입
- `data:` 줄 — JSON 데이터
- 빈 줄 — 이벤트 구분자

---

## 3. Anthropic 스트리밍 이벤트 타입

스트리밍을 활성화하려면 요청 바디에 `"stream": true`를 추가한다.

### 이벤트 순서

```
message_start
content_block_start  (index: 0)
ping
content_block_delta  (text_delta: "안")
content_block_delta  (text_delta: "녕")
content_block_delta  (text_delta: "하세요")
content_block_stop   (index: 0)
message_delta        (stop_reason, usage)
message_stop
```

### 이벤트별 데이터 구조

#### `message_start`

```json
{
  "type": "message_start",
  "message": {
    "id": "msg_01...",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [],
    "stop_reason": null,
    "usage": { "input_tokens": 25, "output_tokens": 1 }
  }
}
```

#### `content_block_start`

```json
{
  "type": "content_block_start",
  "index": 0,
  "content_block": { "type": "text", "text": "" }
}
```

tool_use 블록의 경우:
```json
{
  "type": "content_block_start",
  "index": 1,
  "content_block": {
    "type": "tool_use",
    "id": "toolu_01...",
    "name": "read_file",
    "input": {}
  }
}
```

#### `content_block_delta`

텍스트 델타:
```json
{
  "type": "content_block_delta",
  "index": 0,
  "delta": { "type": "text_delta", "text": "안녕" }
}
```

도구 입력 델타 (JSON이 점진적으로 도착):
```json
{
  "type": "content_block_delta",
  "index": 1,
  "delta": { "type": "input_json_delta", "partial_json": "{\"path\": \"./src" }
}
```

#### `message_delta` (최종)

```json
{
  "type": "message_delta",
  "delta": { "stop_reason": "tool_use", "stop_sequence": null },
  "usage": { "output_tokens": 89 }
}
```

---

## 4. 스트리밍 이벤트 파싱 상태 기계

스트리밍 응답을 조립하려면 상태 기계(state machine)가 필요하다:

```
초기 상태
    │
    ▼ message_start
메시지 수신 중
    │
    ├─ content_block_start (type=text) ──────→ 텍스트 블록 수신 중
    │       │ content_block_delta (text_delta)    (텍스트 누적)
    │       │ content_block_stop                  (블록 완성)
    │       └──────────────────────────────────────┘
    │
    ├─ content_block_start (type=tool_use) ──→ 도구 블록 수신 중
    │       │ content_block_delta (input_json_delta) (JSON 누적)
    │       │ content_block_stop                     (JSON 완성, 파싱)
    │       └──────────────────────────────────────────┘
    │
    ▼ message_stop
완료
```

---

## 5. Kotlin 구현 (Ktor)

```kotlin
suspend fun createMessageStreaming(
    messages: List<Message>,
    tools: List<Tool>,
    model: String,
    onText: (String) -> Unit,               // 텍스트 토큰 콜백
    onToolCall: (ToolUse) -> Unit            // 도구 호출 완성 콜백
) {
    // 조립 중인 상태
    val textBuilders = mutableMapOf<Int, StringBuilder>()
    val toolBuilders = mutableMapOf<Int, ToolUseBuilder>()

    httpClient.preparePost("https://api.anthropic.com/v1/messages") {
        header("x-api-key", apiKey)
        header("anthropic-version", "2023-06-01")
        contentType(ContentType.Application.Json)
        setBody(MessageRequest(model, messages, tools, stream = true))
    }.execute { response ->
        // SSE 스트림 읽기
        val channel = response.bodyAsChannel()
        while (!channel.isClosedForRead) {
            val line = channel.readUTF8Line() ?: break
            
            if (line.startsWith("data: ")) {
                val data = line.removePrefix("data: ")
                if (data == "[DONE]") break  // OpenAI 호환, Anthropic에선 message_stop 사용
                
                val event = Json.parseToJsonElement(data).jsonObject
                handleStreamEvent(event, textBuilders, toolBuilders, onText, onToolCall)
            }
        }
    }
}

fun handleStreamEvent(
    event: JsonObject,
    textBuilders: MutableMap<Int, StringBuilder>,
    toolBuilders: MutableMap<Int, ToolUseBuilder>,
    onText: (String) -> Unit,
    onToolCall: (ToolUse) -> Unit
) {
    when (event["type"]?.jsonPrimitive?.content) {
        "content_block_start" -> {
            val index = event["index"]!!.jsonPrimitive.int
            val block = event["content_block"]!!.jsonObject
            when (block["type"]?.jsonPrimitive?.content) {
                "text" -> textBuilders[index] = StringBuilder()
                "tool_use" -> toolBuilders[index] = ToolUseBuilder(
                    id = block["id"]!!.jsonPrimitive.content,
                    name = block["name"]!!.jsonPrimitive.content
                )
            }
        }

        "content_block_delta" -> {
            val index = event["index"]!!.jsonPrimitive.int
            val delta = event["delta"]!!.jsonObject
            when (delta["type"]?.jsonPrimitive?.content) {
                "text_delta" -> {
                    val text = delta["text"]!!.jsonPrimitive.content
                    textBuilders[index]?.append(text)
                    onText(text)                    // 즉시 화면에 출력
                }
                "input_json_delta" -> {
                    val partial = delta["partial_json"]!!.jsonPrimitive.content
                    toolBuilders[index]?.jsonBuilder?.append(partial)
                }
            }
        }

        "content_block_stop" -> {
            val index = event["index"]!!.jsonPrimitive.int
            // 도구 블록 완성: JSON 파싱
            toolBuilders[index]?.let { builder ->
                val input = Json.parseToJsonElement(
                    builder.jsonBuilder.toString()
                ).jsonObject
                onToolCall(ToolUse(builder.id, builder.name, input))
            }
        }
    }
}

data class ToolUseBuilder(
    val id: String,
    val name: String,
    val jsonBuilder: StringBuilder = StringBuilder()
)
```

---

## 6. 터미널 출력

스트리밍의 핵심은 토큰이 도착하는 즉시 출력하는 것:

```kotlin
// 단순 print (줄바꿈 없음, flush 필요)
fun streamToTerminal(token: String) {
    print(token)
    System.out.flush()    // 버퍼를 즉시 비워 화면에 표시
}

// Phase 6에서 Mordant로 개선:
// - 색상 구분 (도구 호출은 다른 색)
// - 진행 표시기
// - diff 하이라이팅
```

---

## 7. 스트리밍 vs 비스트리밍 선택

| 상황 | 권장 방식 |
|---|---|
| 대화형 터미널 UI | **스트리밍** — 사용자 체감 속도 개선 |
| 서브에이전트 (결과만 필요) | **비스트리밍** — 완성된 결과만 필요 |
| 배치 처리 | **비스트리밍** — 처리량 최적화 |
| 토큰 사용량 추적 | 둘 다 가능 (message_delta에서 usage 확인) |

---

## 8. 스트리밍 중 도구 호출 처리

도구 호출이 스트리밍으로 도착할 때의 흐름:

```
content_block_start  → tool_use 블록 시작 (id, name 도착)
content_block_delta  → {"path": "./src  (JSON 조각 1)
content_block_delta  → /main"}          (JSON 조각 2)  
content_block_stop   → JSON 완성 → 파싱 → runTool() 호출
```

도구 입력 JSON이 스트리밍으로 조각나서 도착하므로,
완전한 JSON이 될 때까지 StringBuilder에 누적한 후 파싱해야 한다.

---

## 9. 에러 처리

```kotlin
try {
    createMessageStreaming(...)
} catch (e: IOException) {
    // 네트워크 중단: 재연결 또는 재시도
    println("스트리밍 연결 끊김: ${e.message}")
} catch (e: JsonParseException) {
    // SSE 데이터 파싱 실패: 해당 이벤트 스킵
    println("스트리밍 파싱 오류: ${e.message}")
}
```

스트리밍 중 네트워크가 끊기면 부분적으로 생성된 메시지를 버리고 재시도해야 한다.
(Anthropic API에 스트리밍 재개 기능은 없으므로 처음부터 다시 요청)

---

## References

- [Anthropic Streaming Messages Documentation](https://docs.anthropic.com/en/api/messages-streaming)
- [Server-Sent Events Specification (W3C)](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [Ktor Client Streaming](https://ktor.io/docs/client-responses.html#streaming)
- [DEV: Streaming Tool Calls — Parse Anthropic SSE](https://dev.to/gabrielanhaia/streaming-tool-calls-parse-anthropic-sse-without-loading-the-whole-message-2on)
