# 승인 게이트와 안전장치 (Approval Gates & Safety)

> **한 줄 요약**: `run_tool()` 실행 전에 위험 동작을 가로채서 사용자 확인을 받는 게이트.
> 이 앱 자체가 실제 파일시스템을 만지므로, 진짜로 구현해야 한다.

---

## 1. 왜 안전장치가 필수인가

bomini는 실제 파일시스템에서 동작한다.
`write_file`, `run_bash("rm -rf ...")` 등이 실제로 파일을 삭제하거나 덮어쓴다.

모델이 실수하거나 의도와 다른 동작을 할 수 있다:
- `edit_file`로 특정 줄을 수정하려다 전체 파일 내용 교체
- `run_bash`에 잘못된 인자 — `rm -rf ./build` 대신 `rm -rf /build`
- 의도치 않은 시스템 파일 접근

**"실수가 돌이킬 수 없다면 확인이 필요하다"**가 설계 원칙이다.

---

## 2. 위험도 분류

```kotlin
enum class RiskLevel {
    SAFE,       // 확인 없이 실행 (읽기 전용)
    LOW,        // 경고 표시 후 자동 진행
    MEDIUM,     // 사용자 확인 필요
    HIGH,       // 명시적 확인 필요, 결과 미리보기 표시
    BLOCKED     // 항상 차단 (매우 위험한 패턴)
}

fun assessRisk(toolName: String, input: JsonObject): RiskLevel {
    return when (toolName) {
        // SAFE: 읽기 전용
        "read_file", "list_dir", "grep" -> RiskLevel.SAFE
        
        // SAFE: 읽기 전용 bash
        "run_bash" -> assessBashRisk(input["command"]!!.jsonPrimitive.content)
        
        // MEDIUM: 파일 쓰기/수정
        "write_file" -> if (File(input["path"]!!.jsonPrimitive.content).exists())
            RiskLevel.HIGH    // 덮어쓰기
        else
            RiskLevel.MEDIUM  // 새 파일 생성
        
        "edit_file" -> RiskLevel.MEDIUM
        
        else -> RiskLevel.MEDIUM
    }
}

fun assessBashRisk(command: String): RiskLevel {
    return when {
        // BLOCKED: 절대 실행 불가
        Regex("""rm\s+-rf\s+/[^a-z]""").containsMatchIn(command) -> RiskLevel.BLOCKED
        Regex(""">\s*/dev/sda""").containsMatchIn(command) -> RiskLevel.BLOCKED
        Regex("""chmod\s+-R\s+777\s+/""").containsMatchIn(command) -> RiskLevel.BLOCKED
        
        // HIGH: 위험한 패턴
        command.contains("rm -rf") -> RiskLevel.HIGH
        command.contains("sudo") -> RiskLevel.HIGH
        command.contains("curl") && command.contains("|") && command.contains("sh") -> RiskLevel.HIGH
        command.contains("mkfs") -> RiskLevel.HIGH
        
        // MEDIUM: 주의 필요
        command.contains("rm ") -> RiskLevel.MEDIUM
        command.contains("mv ") -> RiskLevel.MEDIUM
        command.contains("kill ") -> RiskLevel.MEDIUM
        
        // SAFE: 읽기 전용
        command.startsWith("ls") || command.startsWith("cat") ||
        command.startsWith("grep") || command.startsWith("find") ||
        command.startsWith("git log") || command.startsWith("git status") ||
        command.startsWith("git diff") -> RiskLevel.SAFE
        
        // 기본: LOW (불확실)
        else -> RiskLevel.LOW
    }
}
```

---

## 3. 승인 게이트 구현

```kotlin
class ApprovalGate(private val autoApproveLevel: RiskLevel = RiskLevel.LOW) {
    
    fun check(toolName: String, input: JsonObject): ApprovalResult {
        val risk = assessRisk(toolName, input)
        
        return when {
            risk == RiskLevel.BLOCKED -> {
                println("\n[BLOCKED] 이 동작은 허용되지 않습니다:")
                printToolPreview(toolName, input)
                ApprovalResult.Denied("보안 정책에 의해 차단됨")
            }
            
            risk.ordinal <= autoApproveLevel.ordinal -> {
                // 자동 승인 (위험도가 임계값 이하)
                ApprovalResult.Approved
            }
            
            else -> {
                // 사용자 확인 요청
                requestUserApproval(toolName, input, risk)
            }
        }
    }
    
    private fun requestUserApproval(
        toolName: String,
        input: JsonObject,
        risk: RiskLevel
    ): ApprovalResult {
        println()
        println("┌─────────────────────────────────────────┐")
        println("│  ${risk.emoji} 확인 필요 (${risk.displayName})${" ".repeat(20 - risk.displayName.length)}│")
        println("├─────────────────────────────────────────┤")
        printToolPreview(toolName, input)
        println("└─────────────────────────────────────────┘")
        println()
        print("실행하겠습니까? [y/N/e(설명)]: ")
        
        return when (readLine()?.trim()?.lowercase()) {
            "y", "yes" -> ApprovalResult.Approved
            "e", "explain" -> {
                // 모델에게 이 동작의 의도를 설명하도록 요청
                ApprovalResult.NeedExplanation
            }
            else -> ApprovalResult.Denied("사용자가 거부함")
        }
    }
    
    private fun printToolPreview(toolName: String, input: JsonObject) {
        when (toolName) {
            "run_bash" -> {
                println("│  명령: ${input["command"]!!.jsonPrimitive.content}")
            }
            "write_file" -> {
                val path = input["path"]!!.jsonPrimitive.content
                val content = input["content"]!!.jsonPrimitive.content
                val isOverwrite = File(path).exists()
                println("│  파일: $path ${if (isOverwrite) "(덮어쓰기)" else "(새 파일)"}")
                println("│  내용 미리보기:")
                content.lines().take(5).forEach { println("│    $line") }
                if (content.lines().size > 5) println("│    ... (${content.lines().size}줄)")
            }
            "edit_file" -> {
                println("│  파일: ${input["path"]!!.jsonPrimitive.content}")
                println("│  변경:")
                println("│  - ${input["old_string"]!!.jsonPrimitive.content.take(80)}")
                println("│  + ${input["new_string"]!!.jsonPrimitive.content.take(80)}")
            }
        }
    }
}

sealed class ApprovalResult {
    object Approved : ApprovalResult()
    data class Denied(val reason: String) : ApprovalResult()
    object NeedExplanation : ApprovalResult()
}

val RiskLevel.emoji get() = when (this) {
    RiskLevel.SAFE -> "✓"
    RiskLevel.LOW -> "ℹ"
    RiskLevel.MEDIUM -> "⚠"
    RiskLevel.HIGH -> "⚡"
    RiskLevel.BLOCKED -> "✗"
}
```

---

## 4. 에이전트 루프에 게이트 통합

```kotlin
fun runToolWithGate(call: ToolUse, gate: ApprovalGate): ToolResult {
    // 승인 게이트 체크
    when (val approval = gate.check(call.name, call.input)) {
        is ApprovalResult.Denied -> {
            return ToolResult(
                toolUseId = call.id,
                content = "실행 거부됨: ${approval.reason}",
                isError = true
            )
        }
        is ApprovalResult.NeedExplanation -> {
            // 설명 요청 시 모델에게 맥락 추가 요청
            return ToolResult(
                toolUseId = call.id,
                content = "설명: 이 동작이 필요한 이유를 먼저 설명해주세요.",
                isError = false
            )
        }
        is ApprovalResult.Approved -> { /* 계속 진행 */ }
    }
    
    return dispatcher.execute(call)
}
```

---

## 5. 권한 모드 (Permission Modes)

Claude Code의 권한 모드를 참고:

```kotlin
enum class PermissionMode {
    DEFAULT,       // 기본: MEDIUM 이상 확인
    AUTO_APPROVE,  // 자동 승인: 위험 동작도 자동 실행 (위험!)
    PARANOID,      // 모든 도구 확인
    READ_ONLY      // 읽기 도구만 허용
}

class ApprovalGate(val mode: PermissionMode) {
    fun check(toolName: String, input: JsonObject): ApprovalResult {
        return when (mode) {
            PermissionMode.READ_ONLY -> {
                if (toolName in listOf("read_file", "list_dir", "grep"))
                    ApprovalResult.Approved
                else
                    ApprovalResult.Denied("읽기 전용 모드")
            }
            PermissionMode.AUTO_APPROVE -> ApprovalResult.Approved
            PermissionMode.PARANOID -> requestUserApproval(toolName, input, RiskLevel.LOW)
            PermissionMode.DEFAULT -> defaultCheck(toolName, input)
        }
    }
}
```

---

## 6. 허용 목록 (Allowlist)

자주 승인하는 패턴을 미리 허용 목록에 추가:

```json
// .bomini/settings.json
{
  "allowedTools": ["read_file", "list_dir", "grep"],
  "allowedBashPatterns": [
    "git log",
    "git status",
    "git diff",
    "./gradlew build",
    "./gradlew test"
  ],
  "blockedBashPatterns": [
    "rm -rf /",
    "sudo rm"
  ]
}
```

```kotlin
// 허용 목록 기반 자동 승인
fun checkAllowlist(command: String, allowedPatterns: List<String>): Boolean {
    return allowedPatterns.any { pattern ->
        command.trim().startsWith(pattern)
    }
}
```

---

## 7. 위험 감지 패턴 목록

### Bash 위험 패턴

```kotlin
val ALWAYS_BLOCKED = listOf(
    """rm\s+-rf\s+/[^a-zA-Z]""",    // rm -rf / 또는 /etc 등
    """>>\s*/dev/sda""",             // 디스크에 직접 쓰기
    """:()\{.*\}""",                 // Fork bomb
    """dd\s+if=.*of=/dev""",         // 디스크 복사
    """chmod\s+-R\s+777\s+/"""       // 루트 권한 777
)

val HIGH_RISK = listOf(
    """rm\s+-rf""",                  // 재귀 삭제
    """sudo""",                      // 루트 권한
    """curl.*\|\s*sh""",             // curl pipe to shell
    """wget.*\|\s*sh""",             // wget pipe to shell
    """mkfs""",                      // 파일시스템 생성
    """dd\s+if=""",                  // 디스크 작업
    """passwd""",                    // 패스워드 변경
    """useradd""",                   // 사용자 추가
    """crontab"""                    // 크론 수정
)
```

---

## 8. 감사 로그 (Audit Log)

위험 동작의 승인/거부 이력을 로깅:

```kotlin
data class AuditEntry(
    val timestamp: Long,
    val toolName: String,
    val toolInput: String,
    val riskLevel: RiskLevel,
    val decision: String,   // "approved", "denied", "blocked"
    val sessionId: String
)

class AuditLogger(private val logFile: File) {
    fun log(entry: AuditEntry) {
        logFile.appendText(
            "${Json.encodeToString(entry)}\n"
        )
    }
}
```

---

## References

- [Claude Code Permission System](https://docs.anthropic.com/en/docs/claude-code/security)
- [OWASP Top 10 Command Injection](https://owasp.org/www-community/attacks/Command_Injection)
- [Principle of Least Privilege](https://en.wikipedia.org/wiki/Principle_of_least_privilege)
- [Linux capabilities — minimal privilege](https://man7.org/linux/man-pages/man7/capabilities.7.html)
