# 터미널 UI (Terminal User Interface)

> **한 줄 요약**: 초반엔 `println`으로 충분. Phase 6에서 색상/diff/진행 표시로 보강.
> TUI의 목적은 에이전트 상태를 사람이 읽기 쉽게 표현하는 것이다.

---

## 1. 터미널 UI의 역할

에이전트 루프가 돌아가는 동안 사용자에게 보여줄 것들:

```
1. 사용자 입력 프롬프트
2. 모델 응답 (스트리밍)
3. 도구 호출 표시 ("read_file 실행 중...")
4. 도구 결과 (선택: 보여줄지 숨길지)
5. 에러 메시지
6. 진행 표시기 (로딩 스피너)
7. 토큰/비용 정보
8. 승인 요청
```

---

## 2. Phase 1: 최소 출력 (println)

```kotlin
fun main() {
    print("bomini> ")
    val userInput = readLine() ?: return
    
    agent(
        userMessage = userInput,
        onToken = { token -> print(token); System.out.flush() },
        onToolCall = { call -> println("\n[${call.name}(${call.input})]") },
        onToolResult = { result -> /* 숨김 또는 표시 */ }
    )
    
    println()  // 응답 후 줄바꿈
}
```

이것으로도 동작하는 에이전트가 된다.

---

## 3. ANSI 이스케이프 코드

터미널 색상과 스타일은 ANSI 이스케이프 시퀀스로 제어한다:

```kotlin
object AnsiColors {
    const val RESET = "[0m"
    const val BOLD = "[1m"
    const val DIM = "[2m"
    const val ITALIC = "[3m"
    const val UNDERLINE = "[4m"
    
    // 전경색
    const val BLACK = "[30m"
    const val RED = "[31m"
    const val GREEN = "[32m"
    const val YELLOW = "[33m"
    const val BLUE = "[34m"
    const val MAGENTA = "[35m"
    const val CYAN = "[36m"
    const val WHITE = "[37m"
    
    // 배경색
    const val BG_GREEN = "[42m"
    const val BG_RED = "[41m"
    
    fun colored(text: String, color: String) = "$color$text$RESET"
    fun bold(text: String) = "$BOLD$text$RESET"
    fun dim(text: String) = "$DIM$text$RESET"
}

// 사용 예
println(AnsiColors.colored("✓ 파일 생성 완료", AnsiColors.GREEN))
println(AnsiColors.colored("✗ 에러 발생", AnsiColors.RED))
println(AnsiColors.colored("[read_file]", AnsiColors.CYAN))
```

---

## 4. UI 컴포넌트들

### 스피너 (로딩 표시기)

```kotlin
class Spinner(private val message: String = "생각 중") {
    private val frames = listOf("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    private var running = false
    private var thread: Thread? = null

    fun start() {
        running = true
        thread = Thread {
            var i = 0
            while (running) {
                print("\r${frames[i % frames.size]} $message")
                System.out.flush()
                Thread.sleep(80)
                i++
            }
            // 지우기
            print("\r${" ".repeat(message.length + 5)}\r")
            System.out.flush()
        }
        thread?.start()
    }

    fun stop() {
        running = false
        thread?.join()
    }
}

// 사용
val spinner = Spinner("모델 응답 대기 중")
spinner.start()
val response = client.createMessage(...)
spinner.stop()
```

### Diff 표시

```kotlin
fun printDiff(oldContent: String, newContent: String) {
    val oldLines = oldContent.lines()
    val newLines = newContent.lines()
    
    // 간단한 라인 기반 diff
    val diff = computeDiff(oldLines, newLines)
    
    diff.forEach { change ->
        when (change.type) {
            DiffType.UNCHANGED -> println("  ${change.line}")
            DiffType.ADDED -> println(AnsiColors.colored("+ ${change.line}", AnsiColors.GREEN))
            DiffType.REMOVED -> println(AnsiColors.colored("- ${change.line}", AnsiColors.RED))
        }
    }
}
```

### 박스 그리기

```kotlin
fun printBox(title: String, content: String, width: Int = 60) {
    val border = "─".repeat(width - 2)
    println("┌─$border─┐")
    println("│ ${title.padEnd(width - 2)} │")
    println("├─$border─┤")
    content.lines().forEach { line ->
        println("│ ${line.padEnd(width - 2)} │")
    }
    println("└─$border─┘")
}
```

---

## 5. 대화 렌더링

```kotlin
fun renderConversation(messages: List<Message>) {
    messages.forEach { msg ->
        when (msg.role) {
            "user" -> {
                println()
                print(AnsiColors.colored("You: ", AnsiColors.BOLD + AnsiColors.BLUE))
                println(msg.textContent)
            }
            "assistant" -> {
                println()
                print(AnsiColors.colored("bomini: ", AnsiColors.BOLD + AnsiColors.GREEN))
                msg.content.forEach { block ->
                    when (block) {
                        is ContentBlock.Text -> print(block.text)
                        is ContentBlock.ToolUse -> {
                            println()
                            println(AnsiColors.colored(
                                "  → ${block.name}(${block.input.summarize()})",
                                AnsiColors.DIM + AnsiColors.CYAN
                            ))
                        }
                    }
                }
                println()
            }
        }
    }
}
```

---

## 6. Mordant 라이브러리 (Phase 6)

Mordant는 Kotlin용 터미널 UI 라이브러리다:

```kotlin
// build.gradle.kts
implementation("com.github.ajalt.mordant:mordant:2.5.0")

// 사용
import com.github.ajalt.mordant.rendering.TextColors.*
import com.github.ajalt.mordant.rendering.TextStyles.*
import com.github.ajalt.mordant.terminal.Terminal

val t = Terminal()

// 색상
t.println(green("✓ 성공"))
t.println(red("✗ 실패"))
t.println(yellow("⚠ 경고"))

// 스타일
t.println(bold("굵게"))
t.println(italic("기울임"))
t.println(dim("흐리게"))

// 조합
t.println(bold + cyan on white)("중요한 내용")

// 테이블
val table = table {
    header { row("파일", "크기", "수정일") }
    body {
        row("README.md", "2.5 KB", "오늘")
        row("Main.kt", "1.2 KB", "1시간 전")
    }
}
t.println(table)

// 진행 표시기
val progress = progressAnimation {
    text("처리 중")
    percentage()
    progressBar()
    completed()
}
```

---

## 7. 터미널 입력 처리

### REPL 루프

```kotlin
fun runRepl(agent: AgentRunner) {
    println("""
        bomini v0.1.0 — 터미널 코딩 에이전트
        /help: 도움말  /model: 모델 변경  /exit: 종료
    """.trimIndent())
    
    while (true) {
        print("\n${AnsiColors.colored("bomini>", AnsiColors.BOLD + AnsiColors.GREEN)} ")
        val input = readLine() ?: break
        
        if (input.isBlank()) continue
        
        // 슬래시 커맨드 처리
        if (input.startsWith("/")) {
            when (input.trim()) {
                "/exit", "/quit" -> break
                "/help" -> printHelp()
                "/model" -> printCurrentModel()
                else -> agent.handleSlashCommand(input)
            }
            continue
        }
        
        // 에이전트 실행
        try {
            agent.run(input)
        } catch (e: InterruptedException) {
            println("\n[중단됨]")
        }
    }
    
    println("bomini 종료.")
}
```

### 키보드 인터럽트 (Ctrl+C)

```kotlin
// JVM의 ShutdownHook으로 처리
Runtime.getRuntime().addShutdownHook(Thread {
    println("\n[세션 저장 중...]")
    sessionManager.save(currentSession)
    println("[완료]")
})

// 실행 중 Ctrl+C
val agentJob = launch { agent.run(userMessage) }
// 다음 입력이 올 때 agentJob.cancel()
```

---

## 8. 토큰/비용 표시

```kotlin
fun printUsageSummary(usage: Usage, model: ClaudeModel) {
    val inputCost = usage.inputTokens / 1_000_000.0 * model.inputCostPerMTok
    val outputCost = usage.outputTokens / 1_000_000.0 * model.outputCostPerMTok
    
    println(AnsiColors.dim(
        "tokens: ↑${usage.inputTokens} ↓${usage.outputTokens} " +
        "cost: \${"%.4f".format(inputCost + outputCost)}"
    ))
}

// 출력 예:
// tokens: ↑4523 ↓287 cost: $0.0179
```

---

## 9. 터미널 너비에 맞게 조정

```kotlin
fun getTerminalWidth(): Int {
    return try {
        val size = ProcessBuilder("stty", "size")
            .redirectInput(File("/dev/tty"))
            .start().inputStream.readText().trim()
        size.split(" ")[1].toInt()
    } catch (e: Exception) {
        80  // 기본값
    }
}

fun truncateLine(text: String, maxWidth: Int = getTerminalWidth() - 4): String {
    return if (text.length > maxWidth) text.take(maxWidth - 3) + "..." else text
}
```

---

## References

- [Mordant — Kotlin Terminal Library](https://github.com/ajalt/mordant)
- [ANSI Escape Codes Reference](https://en.wikipedia.org/wiki/ANSI_escape_code)
- [JLine3 — Advanced Terminal Handling for JVM](https://github.com/jline/jline3)
- [Building CLI Apps in Kotlin (JetBrains)](https://kotlinlang.org/docs/command-line.html)
- [Clikt — Kotlin CLI Framework](https://github.com/ajalt/clikt)
