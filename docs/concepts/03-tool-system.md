# 도구 시스템 (Tool Definition & Dispatcher)

> **한 줄 요약**: 도구란 "모델이 부를 수 있는 함수의 스키마 + 실제 실행 코드"의 쌍이다.
> 모델은 스키마(메뉴판)를 보고 선택하고, 실행은 harness가 한다.

---

## 1. 도구의 본질

도구(Tool)는 두 부분으로 이루어진다:

```
도구 = 스키마(Schema) + 구현(Implementation)
         ↓                    ↓
   모델이 읽는 것         harness가 실행하는 것
   (JSON Schema)          (실제 코드)
```

**스키마**: 모델에게 "이런 이름의 도구가 있고, 이런 인자를 넣어서 부를 수 있어"라고 알려주는 메타데이터.
**구현**: 모델이 도구 호출을 "요청"했을 때, harness가 실제로 실행하는 코드.

중요한 구분:
- 모델은 도구를 **직접 실행하지 않는다.**
- 모델은 "이 도구를 이 인자로 실행하고 싶다"는 **의사를 텍스트(JSON)로 표현**할 뿐이다.
- 실제 실행 권한은 항상 harness에 있다.

---

## 2. 도구 스키마 (JSON Schema 기반)

Anthropic API의 도구 정의 포맷:

```json
{
  "name": "read_file",
  "description": "Read the complete contents of a file from the filesystem. Use this when you need to examine file contents.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "The absolute or relative path to the file to read"
      }
    },
    "required": ["path"]
  }
}
```

### 필드 설명

| 필드 | 역할 | 중요도 |
|---|---|---|
| `name` | 도구의 고유 식별자. 모델이 호출 시 이 이름을 사용 | 필수 |
| `description` | 모델이 **언제 이 도구를 써야 하는지** 판단하는 근거 | **매우 중요** |
| `input_schema` | 도구에 전달할 인자의 JSON Schema 정의 | 필수 |

### description이 중요한 이유

모델은 description을 읽고 "지금 상황에서 이 도구를 써야 하는가"를 **확률적으로** 판단한다.
description이 명확할수록 모델이 적절한 상황에서 도구를 호출한다.

```
나쁜 description: "파일을 읽는다"
좋은 description: "파일시스템에서 파일의 전체 내용을 읽는다. 
                  파일 내용을 검사하거나 분석해야 할 때 사용한다."
```

---

## 3. JSON Schema 기초

도구 인자는 JSON Schema Draft 7 형식으로 정의한다.

### 기본 타입

```json
{
  "type": "object",
  "properties": {
    "path":    { "type": "string" },
    "limit":   { "type": "integer", "minimum": 1 },
    "recurse": { "type": "boolean", "default": false },
    "mode":    { "type": "string", "enum": ["read", "write", "append"] }
  },
  "required": ["path"]
}
```

### 중첩 객체와 배열

```json
{
  "type": "object",
  "properties": {
    "edits": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "old_string": { "type": "string" },
          "new_string": { "type": "string" }
        },
        "required": ["old_string", "new_string"]
      }
    }
  }
}
```

---

## 4. Kotlin에서의 도구 정의

```kotlin
@Serializable
data class ToolInputSchema(
    val type: String = "object",
    val properties: Map<String, PropertySchema>,
    val required: List<String> = emptyList()
)

@Serializable
data class PropertySchema(
    val type: String,
    val description: String,
    val enum: List<String>? = null,
    val default: JsonElement? = null
)

@Serializable
data class Tool(
    val name: String,
    val description: String,
    @SerialName("input_schema")
    val inputSchema: ToolInputSchema
)

// 도구 정의 예시
val READ_FILE_TOOL = Tool(
    name = "read_file",
    description = """Read the complete contents of a file from the filesystem.
        Use this when you need to examine file contents to understand code,
        check configuration, or read any file content.""",
    inputSchema = ToolInputSchema(
        properties = mapOf(
            "path" to PropertySchema("string", "The path to the file to read"),
            "offset" to PropertySchema("integer", "Line number to start reading from (optional)"),
            "limit" to PropertySchema("integer", "Maximum number of lines to read (optional)")
        ),
        required = listOf("path")
    )
)
```

---

## 5. 도구 실행 디스패처

디스패처는 모델의 tool_use 요청을 받아 실제 함수로 라우팅하는 switch문이다.

```kotlin
// 모델 응답의 tool_use 블록
data class ToolUse(
    val id: String,          // 이 호출의 고유 ID (결과 매핑에 사용)
    val name: String,        // 도구 이름
    val input: JsonObject    // 도구 인자
)

// 디스패처
fun runTool(call: ToolUse): ToolResult {
    val content = try {
        when (call.name) {
            "read_file"  -> ReadFileTool.execute(call.input)
            "write_file" -> WriteFileTool.execute(call.input)
            "edit_file"  -> EditFileTool.execute(call.input)
            "list_dir"   -> ListDirTool.execute(call.input)
            "run_bash"   -> RunBashTool.execute(call.input)
            "grep"       -> GrepTool.execute(call.input)
            else -> "Error: Unknown tool '${call.name}'"
        }
    } catch (e: Exception) {
        "Error executing ${call.name}: ${e.message}"
    }

    return ToolResult(
        toolUseId = call.id,    // 모델이 어느 호출의 결과인지 매핑하기 위해
        content = content
    )
}
```

### 도구 결과 포맷

```kotlin
@Serializable
data class ToolResult(
    @SerialName("tool_use_id")
    val toolUseId: String,
    val content: String,
    @SerialName("is_error")
    val isError: Boolean = false  // 에러 시 true로 설정, 모델이 인식
)
```

---

## 6. 도구 인터페이스 패턴

모든 도구를 동일한 인터페이스로 만들면 디스패처가 단순해진다:

```kotlin
interface ToolExecutor {
    val definition: Tool
    fun execute(input: JsonObject): String
}

class ReadFileTool : ToolExecutor {
    override val definition = Tool(
        name = "read_file",
        description = "Read complete file contents from the filesystem.",
        inputSchema = ToolInputSchema(
            properties = mapOf(
                "path" to PropertySchema("string", "File path to read")
            ),
            required = listOf("path")
        )
    )

    override fun execute(input: JsonObject): String {
        val path = input["path"]?.jsonPrimitive?.content
            ?: return "Error: 'path' is required"
        return try {
            File(path).readText()
        } catch (e: Exception) {
            "Error reading file: ${e.message}"
        }
    }
}

// 디스패처 (인터페이스 기반)
class ToolDispatcher(private val tools: List<ToolExecutor>) {
    private val toolMap = tools.associateBy { it.definition.name }

    fun execute(call: ToolUse): ToolResult {
        val executor = toolMap[call.name]
            ?: return ToolResult(call.id, "Unknown tool: ${call.name}", isError = true)
        val content = executor.execute(call.input)
        return ToolResult(call.id, content)
    }

    fun getDefinitions() = tools.map { it.definition }
}
```

---

## 7. 병렬 도구 실행

모델이 한 번의 응답에서 여러 tool_use를 보낼 수 있다.
이것들이 서로 의존성이 없다면 병렬로 실행할 수 있다:

```kotlin
// 여러 도구 결과 포맷 (API에 한꺼번에 보냄)
suspend fun runTools(calls: List<ToolUse>): Message {
    val results = calls.map { call ->
        // 코루틴으로 병렬 실행
        async { dispatcher.execute(call) }
    }.awaitAll()

    return Message(
        role = "user",
        content = results.map { result ->
            ContentBlock.ToolResult(
                toolUseId = result.toolUseId,
                content = result.content
            )
        }
    )
}
```

---

## 8. 도구 설계 원칙

### 단일 책임

각 도구는 하나의 명확한 기능만 수행한다.
`read_and_search_file`처럼 두 기능을 합치지 않는다. 모델이 스스로 두 도구를 순서대로 호출하면 된다.

### 멱등성(Idempotency)

읽기 도구(read_file, list_dir, grep)는 멱등성을 가져야 한다.
같은 인자로 여러 번 호출해도 결과가 같아야 한다.

### 명확한 에러 메시지

도구가 실패할 때, 모델이 원인을 이해하고 다른 방법을 선택할 수 있도록 명확한 에러 메시지를 반환한다:

```kotlin
// 나쁜 예
return "Error"

// 좋은 예
return "Error: File not found at path '${path}'. " +
       "Use list_dir to check what files exist in the directory."
```

### 크기 제한

대용량 파일을 통째로 반환하면 context window를 낭비한다:

```kotlin
fun readFile(path: String, offset: Int = 0, limit: Int = 2000): String {
    val lines = File(path).readLines()
    val total = lines.size
    val result = lines.drop(offset).take(limit)
    val suffix = if (offset + limit < total) 
        "\n... (${total - offset - limit} more lines, use offset=${offset + limit} to continue)"
    else ""
    return result.joinToString("\n") + suffix
}
```

---

## 9. 도구 호출 추적 (디버깅)

학습 목적이므로 모든 도구 호출을 로깅한다:

```kotlin
fun runToolWithLogging(call: ToolUse): ToolResult {
    println("\n┌─ TOOL CALL: ${call.name}")
    println("│  Input: ${call.input}")

    val start = System.currentTimeMillis()
    val result = runTool(call)
    val elapsed = System.currentTimeMillis() - start

    println("│  Result (${elapsed}ms): ${result.content.take(200)}")
    println("└─────────────────")

    return result
}
```

---

## References

- [Anthropic Tool Use Guide](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [JSON Schema Specification](https://json-schema.org/specification)
- [JSON Schema Draft 7 Reference](https://json-schema.org/draft-07/json-schema-validation)
- [Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Function Calling Best Practices (OpenAI, 유사 개념)](https://platform.openai.com/docs/guides/function-calling/best-practices)
