# 훅 (Hooks)

> **한 줄 요약**: 도구 실행 전/후, 세션 시작/종료 등 에이전트 라이프사이클의
> 특정 지점에 끼워넣는 콜백. LLM과 무관한 순수 코드다.

---

## 1. 훅의 본질

훅은 에이전트 루프의 **특정 이벤트에 반응하는 콜백 함수**다.

```
에이전트 루프
    │
    ├─ 세션 시작 ──────────────── [onSessionStart 훅]
    │
    ├─ 도구 실행 요청
    │   ├── before ────────────── [beforeToolCall 훅]  ← 여기서 승인/차단 가능
    │   ├── 도구 실행
    │   └── after ─────────────── [afterToolCall 훅]   ← 여기서 로깅/알림
    │
    ├─ 모델 응답 수신 ─────────── [onResponse 훅]
    │
    └─ 세션 종료 ──────────────── [onSessionStop 훅]
```

훅은 **LLM과 완전히 독립적**이다.
LLM이 뭘 호출했는지 결과를 확인하고 알림을 보내거나, 위험 동작을 차단하거나,
로그를 남기는 등의 "순수 로직"이다.

---

## 2. Claude Code의 훅 이벤트

Claude Code는 다음 이벤트에 훅을 지원한다:

| 이벤트 | 설명 |
|---|---|
| `PreToolUse` | 도구 실행 직전. 차단(block) 가능 |
| `PostToolUse` | 도구 실행 직후. 결과 확인 가능 |
| `Notification` | 알림 발생 시 |
| `Stop` | 에이전트 루프 종료 시 |
| `SubagentStop` | 서브에이전트 종료 시 |
| `UserPromptSubmit` | 사용자가 입력을 제출할 때 |

---

## 3. 훅 설정 포맷 (Claude Code)

Claude Code의 훅은 `settings.json`에 정의한다:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/check-dangerous-command.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "git add ."
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.bomini/memo-writer.py"
          }
        ]
      }
    ]
  }
}
```

---

## 4. bomini에서의 훅 구현

### 훅 인터페이스

```kotlin
// 훅 실행 결과
sealed class HookResult {
    object Allow : HookResult()                      // 계속 진행
    data class Block(val reason: String) : HookResult()  // 실행 차단
    data class Modified(val newInput: JsonObject) : HookResult()  // 입력 수정
}

// 훅 타입
interface Hook {
    val name: String
    val event: HookEvent
    fun execute(context: HookContext): HookResult
}

enum class HookEvent {
    PRE_TOOL_USE,
    POST_TOOL_USE,
    SESSION_START,
    SESSION_STOP,
    ON_RESPONSE
}

data class HookContext(
    val event: HookEvent,
    val toolName: String? = null,
    val toolInput: JsonObject? = null,
    val toolResult: String? = null,
    val sessionId: String? = null
)
```

### 훅 레지스트리

```kotlin
class HookRegistry {
    private val hooks = mutableMapOf<HookEvent, MutableList<Hook>>()

    fun register(hook: Hook) {
        hooks.getOrPut(hook.event) { mutableListOf() }.add(hook)
    }

    fun executeHooks(event: HookEvent, context: HookContext): HookResult {
        val eventHooks = hooks[event] ?: return HookResult.Allow
        
        for (hook in eventHooks) {
            val result = hook.execute(context)
            if (result is HookResult.Block) return result  // 하나라도 차단하면 중단
        }
        
        return HookResult.Allow
    }
}
```

### 에이전트 루프에 훅 통합

```kotlin
fun runTool(call: ToolUse, hooks: HookRegistry): ToolResult {
    val context = HookContext(
        event = HookEvent.PRE_TOOL_USE,
        toolName = call.name,
        toolInput = call.input
    )
    
    // PreToolUse 훅 실행
    when (val result = hooks.executeHooks(HookEvent.PRE_TOOL_USE, context)) {
        is HookResult.Block -> {
            return ToolResult(
                toolUseId = call.id,
                content = "도구 실행이 차단됨: ${result.reason}",
                isError = true
            )
        }
        is HookResult.Allow -> { /* 계속 진행 */ }
    }
    
    // 실제 도구 실행
    val toolResult = dispatcher.execute(call)
    
    // PostToolUse 훅 실행
    hooks.executeHooks(HookEvent.POST_TOOL_USE, HookContext(
        event = HookEvent.POST_TOOL_USE,
        toolName = call.name,
        toolInput = call.input,
        toolResult = toolResult.content
    ))
    
    return toolResult
}
```

---

## 5. 훅 사용 예시

### 예시 1: 위험 명령어 차단 훅

```kotlin
class DangerousCommandBlocker : Hook {
    override val name = "DangerousCommandBlocker"
    override val event = HookEvent.PRE_TOOL_USE

    private val patterns = listOf(
        Regex("""rm\s+-rf\s+/"""),
        Regex("""chmod\s+777\s+/"""),
        Regex(""">\s*/dev/sda""")
    )

    override fun execute(context: HookContext): HookResult {
        if (context.toolName != "run_bash") return HookResult.Allow
        
        val command = context.toolInput?.get("command")?.jsonPrimitive?.content
            ?: return HookResult.Allow
        
        val matched = patterns.firstOrNull { it.containsMatchIn(command) }
        return if (matched != null) {
            HookResult.Block("위험한 명령어 패턴 감지: ${matched.pattern}")
        } else {
            HookResult.Allow
        }
    }
}
```

### 예시 2: 도구 호출 로깅 훅

```kotlin
class ToolCallLogger(private val logFile: File) : Hook {
    override val name = "ToolCallLogger"
    override val event = HookEvent.POST_TOOL_USE

    override fun execute(context: HookContext): HookResult {
        val timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME)
        logFile.appendText(
            "[$timestamp] ${context.toolName}: ${context.toolInput}\n"
        )
        return HookResult.Allow
    }
}
```

### 예시 3: 세션 종료 시 메모 작성 훅

```kotlin
class MemoWriterHook(private val memoDir: File) : Hook {
    override val name = "MemoWriter"
    override val event = HookEvent.SESSION_STOP

    override fun execute(context: HookContext): HookResult {
        // Q&A 요약을 메모로 저장
        val sessionId = context.sessionId ?: return HookResult.Allow
        
        // 이것이 이 프로젝트의 stop hook이다!
        // (현재 .claude/settings.json에 이미 구현되어 있음)
        println("세션 ${sessionId} 종료 — 메모 작성 중...")
        
        return HookResult.Allow
    }
}
```

---

## 6. 외부 스크립트 기반 훅

Claude Code처럼 훅을 외부 쉘 스크립트로 구현하면 더 유연하다:

```kotlin
class ShellHook(
    override val name: String,
    override val event: HookEvent,
    private val command: String
) : Hook {
    override fun execute(context: HookContext): HookResult {
        val process = ProcessBuilder("/bin/bash", "-c", command)
            .also { pb ->
                // context 정보를 환경변수로 전달
                pb.environment()["HOOK_TOOL_NAME"] = context.toolName ?: ""
                pb.environment()["HOOK_TOOL_INPUT"] = context.toolInput?.toString() ?: ""
                pb.environment()["HOOK_EVENT"] = context.event.name
            }
            .redirectErrorStream(true)
            .start()

        val exitCode = process.waitFor(5, TimeUnit.SECONDS).let {
            if (!it) { process.destroyForcibly(); return HookResult.Allow }
            process.exitValue()
        }

        val output = process.inputStream.readText()

        return when (exitCode) {
            0 -> HookResult.Allow
            2 -> HookResult.Block(output.trim())  // exit 2 = 차단
            else -> HookResult.Allow
        }
    }
}

// 사용 예:
// exit 0 → 허용
// exit 2 + 메시지 출력 → 차단 (Claude Code 규약)
```

---

## 7. 훅 설정 파일

```json
// .bomini/settings.json
{
  "hooks": [
    {
      "event": "PRE_TOOL_USE",
      "toolPattern": "run_bash",
      "type": "shell",
      "command": "~/.bomini/hooks/check-bash.sh"
    },
    {
      "event": "POST_TOOL_USE",
      "toolPattern": "write_file",
      "type": "shell",
      "command": "git add \"$HOOK_TOOL_INPUT_PATH\""
    },
    {
      "event": "SESSION_STOP",
      "type": "shell",
      "command": "python3 ~/.bomini/hooks/memo-writer.py"
    }
  ]
}
```

---

## 8. 훅 vs 안전장치

| | 훅 | 승인 게이트 |
|---|---|---|
| 주체 | 자동화된 코드/스크립트 | 사용자 (인간) |
| 속도 | 즉각 | 사용자 응답 대기 |
| 적합한 경우 | 알려진 패턴 차단, 로깅 | 모든 파일 삭제, 새로운 상황 |
| 구현 위치 | `run_tool` 전/후 | `run_tool` 전 사용자 확인 |

---

## References

- [Claude Code Hooks Documentation](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Claude Code settings.json Reference](https://docs.anthropic.com/en/docs/claude-code/settings)
- [Webhook Design Patterns](https://webhook.site/docs)
- [Observer Pattern (GoF Design Pattern)](https://refactoring.guru/design-patterns/observer)
