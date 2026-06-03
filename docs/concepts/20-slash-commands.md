# 슬래시 커맨드 (Slash Commands)

> **한 줄 요약**: `/model`, `/compact`, `/clear` 같은 특수 명령.
> REPL 루프에서 LLM을 거치지 않고 직접 처리되는 커맨드다.

---

## 1. 슬래시 커맨드란

일반 사용자 입력은 LLM에게 전달된다:
```
user: "파일 만들어줘" → LLM → tool_use → 파일 생성
```

슬래시 커맨드는 LLM을 거치지 않고 harness가 직접 처리한다:
```
user: "/model opus" → harness → session.currentModel = OPUS_4
user: "/compact"    → harness → compaction 즉시 실행
user: "/clear"      → harness → state 초기화
```

슬래시 커맨드는 **harness 제어 명령**이다.

---

## 2. Claude Code의 내장 슬래시 커맨드

| 커맨드 | 기능 |
|---|---|
| `/help` | 사용 가능한 커맨드 목록 |
| `/model [name]` | 모델 확인 또는 변경 |
| `/compact` | 수동 context 압축 |
| `/clear` | 대화 이력 초기화 |
| `/cost` | 현재 세션 비용 표시 |
| `/status` | 토큰 사용량, 모델 등 상태 |
| `/exit` / `/quit` | bomini 종료 |
| `/history` | 최근 대화 이력 표시 |
| `/sessions` | 저장된 세션 목록 |
| `/resume [id]` | 이전 세션 이어가기 |

---

## 3. 구현

### REPL에서 슬래시 커맨드 감지

```kotlin
fun handleInput(input: String, session: SessionState): InputType {
    return when {
        input.startsWith("/") -> InputType.SlashCommand
        input.isBlank() -> InputType.Empty
        else -> InputType.UserMessage
    }
}

sealed class InputType {
    object SlashCommand : InputType()
    object Empty : InputType()
    object UserMessage : InputType()
}
```

### 커맨드 파서

```kotlin
data class ParsedCommand(
    val name: String,
    val args: List<String>,
    val raw: String
)

fun parseSlashCommand(input: String): ParsedCommand {
    val parts = input.trim().removePrefix("/").split(Regex("\\s+"))
    return ParsedCommand(
        name = parts[0].lowercase(),
        args = parts.drop(1),
        raw = input
    )
}

// "/model opus" → ParsedCommand(name="model", args=["opus"], raw="/model opus")
// "/resume abc123" → ParsedCommand(name="resume", args=["abc123"], ...)
// "/help" → ParsedCommand(name="help", args=[], ...)
```

### 커맨드 핸들러

```kotlin
class SlashCommandHandler(
    private val session: MutableSessionState,
    private val agentRunner: AgentRunner,
    private val sessionManager: SessionManager
) {
    fun handle(command: ParsedCommand): CommandResult {
        return when (command.name) {
            "help", "h" -> handleHelp()
            "model" -> handleModel(command.args)
            "compact" -> handleCompact()
            "clear" -> handleClear()
            "cost" -> handleCost()
            "status" -> handleStatus()
            "sessions", "ls" -> handleListSessions()
            "resume" -> handleResume(command.args)
            "exit", "quit", "q" -> handleExit()
            else -> CommandResult.Unknown(command.name)
        }
    }
    
    private fun handleHelp(): CommandResult {
        println("""
            ┌─────────────────────────────────────────────────┐
            │  bomini 슬래시 커맨드                            │
            ├─────────────────────────────────────────────────┤
            │  /help           — 이 도움말                    │
            │  /model [name]   — 모델 확인/변경               │
            │  /compact        — 컨텍스트 압축                │
            │  /clear          — 대화 이력 초기화             │
            │  /cost           — 세션 비용 표시               │
            │  /status         — 현재 상태                    │
            │  /sessions       — 세션 목록                   │
            │  /resume [id]    — 세션 이어가기                │
            │  /exit           — 종료                         │
            └─────────────────────────────────────────────────┘
        """.trimIndent())
        return CommandResult.Ok
    }
    
    private fun handleModel(args: List<String>): CommandResult {
        if (args.isEmpty()) {
            val model = session.currentModel
            println("현재 모델: ${model.displayName} (${model.id})")
            println("입력 비용: \$${model.inputCostPerMTok}/MTok")
            println("출력 비용: \$${model.outputCostPerMTok}/MTok")
            return CommandResult.Ok
        }
        
        val newModel = ClaudeModel.fromAlias(args[0])
            ?: return CommandResult.Error("알 수 없는 모델: ${args[0]}\n사용 가능: opus, sonnet, haiku")
        
        session.currentModel = newModel
        println("모델 변경: ${newModel.displayName}")
        return CommandResult.Ok
    }
    
    private fun handleCompact(): CommandResult {
        val before = session.messages.size
        val compacted = agentRunner.compact(session.messages)
        session.messages.clear()
        session.messages.addAll(compacted)
        val after = session.messages.size
        println("컨텍스트 압축: $before개 메시지 → $after개 메시지")
        return CommandResult.Ok
    }
    
    private fun handleClear(): CommandResult {
        session.messages.clear()
        println("대화 이력이 초기화되었습니다.")
        return CommandResult.Ok
    }
    
    private fun handleStatus(): CommandResult {
        val estimatedTokens = estimateMessageTokens(session.messages)
        val usagePercent = estimatedTokens * 100 / CONTEXT_WINDOW_SIZE
        
        println("""
            ┌─────────────────────────────────────┐
            │  bomini 상태                         │
            ├─────────────────────────────────────┤
            │  모델:     ${session.currentModel.displayName.padEnd(24)} │
            │  세션:     ${session.id.take(8)}...                    │
            │  메시지:   ${session.messages.size.toString().padEnd(24)} │
            │  토큰:     ~${estimatedTokens} (~${usagePercent}% 사용)
            └─────────────────────────────────────┘
        """.trimIndent())
        return CommandResult.Ok
    }
    
    private fun handleListSessions(): CommandResult {
        val sessions = sessionManager.listSessions()
        if (sessions.isEmpty()) {
            println("저장된 세션이 없습니다.")
            return CommandResult.Ok
        }
        
        println("ID         제목                     모델       업데이트")
        println("─".repeat(60))
        sessions.take(10).forEach { s ->
            println("${s.id.take(8)}  ${s.title.take(20).padEnd(22)} ${s.model.take(8).padEnd(10)} ${s.updatedAt.toRelativeTime()}")
        }
        return CommandResult.Ok
    }
    
    private fun handleResume(args: List<String>): CommandResult {
        val sessionId = args.firstOrNull()
            ?: return CommandResult.Error("세션 ID를 지정해주세요: /resume <id>")
        
        val loaded = sessionManager.load(sessionId)
            ?: return CommandResult.Error("세션을 찾을 수 없습니다: $sessionId")
        
        session.messages.clear()
        session.messages.addAll(loaded.messages)
        session.currentModel = ClaudeModel.fromAlias(loaded.model) ?: ClaudeModel.SONNET_4
        
        println("세션 복원: ${loaded.title} (${loaded.messages.size}개 메시지)")
        return CommandResult.Ok
    }
    
    private fun handleExit(): CommandResult {
        println("세션 저장 중...")
        sessionManager.save(session.toSession())
        println("bomini 종료.")
        return CommandResult.Exit
    }
}

sealed class CommandResult {
    object Ok : CommandResult()
    object Exit : CommandResult()
    data class Error(val message: String) : CommandResult()
    data class Unknown(val name: String) : CommandResult()
}
```

---

## 4. 커스텀 슬래시 커맨드 (스킬 연동)

사용자가 직접 슬래시 커맨드를 정의할 수 있다:

```kotlin
// .bomini/commands/debug.md → /debug 커맨드
// .bomini/commands/review.md → /review 커맨드

class CustomCommandLoader(private val commandsDir: File) {
    fun loadCustomCommands(): Map<String, SkillTool> {
        return commandsDir.listFiles { f -> f.extension == "md" }
            ?.associate { file ->
                val commandName = file.nameWithoutExtension.lowercase()
                commandName to SkillTool(
                    name = commandName,
                    content = file.readText()
                )
            } ?: emptyMap()
    }
}

// REPL에서 커스텀 커맨드 처리
fun handleCustomCommand(name: String, content: String, userArgs: String) {
    // 커스텀 커맨드 내용을 system 프롬프트에 추가해서 모델 호출
    val enhancedState = listOf(
        Message.system(content),
        Message.user(if (userArgs.isNotBlank()) userArgs else "이 커맨드를 실행해줘")
    )
    agentRunner.runWithState(enhancedState)
}
```

---

## 5. 슬래시 커맨드 자동 완성

```kotlin
fun autocomplete(partial: String): List<String> {
    val allCommands = listOf(
        "/help", "/model", "/compact", "/clear", "/cost",
        "/status", "/sessions", "/resume", "/exit"
    ) + customCommandNames.map { "/$it" }
    
    return allCommands.filter { it.startsWith(partial) }
}

// "/mo" → ["/model"]
// "/c" → ["/compact", "/clear", "/cost"]
```

---

## 6. REPL 전체 흐름

```kotlin
fun runRepl() {
    val commandHandler = SlashCommandHandler(session, agentRunner, sessionManager)
    
    while (true) {
        print("\nbomini> ")
        System.out.flush()
        
        val input = readLine() ?: break
        
        when (handleInput(input, session)) {
            InputType.Empty -> continue
            
            InputType.SlashCommand -> {
                val cmd = parseSlashCommand(input)
                when (val result = commandHandler.handle(cmd)) {
                    is CommandResult.Exit -> break
                    is CommandResult.Error -> println("오류: ${result.message}")
                    is CommandResult.Unknown -> {
                        // 커스텀 커맨드 확인
                        val customCmd = customCommands[cmd.name]
                        if (customCmd != null) {
                            handleCustomCommand(cmd.name, customCmd.content, cmd.args.joinToString(" "))
                        } else {
                            println("알 수 없는 커맨드: /${cmd.name}. /help를 입력하세요.")
                        }
                    }
                    CommandResult.Ok -> { /* 완료 */ }
                }
            }
            
            InputType.UserMessage -> {
                agentRunner.run(input)
            }
        }
    }
}
```

---

## References

- [Claude Code Slash Commands](https://docs.anthropic.com/en/docs/claude-code/slash-commands)
- [Claude Code Custom Commands](https://docs.anthropic.com/en/docs/claude-code/slash-commands#user-defined-slash-commands)
- [REPL Design Patterns](https://en.wikipedia.org/wiki/Read%E2%80%93eval%E2%80%93print_loop)
- [Clikt — Kotlin Command-Line Interface](https://github.com/ajalt/clikt)
