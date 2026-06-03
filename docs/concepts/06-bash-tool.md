# Bash 도구 (run_bash)

> **한 줄 요약**: 에이전트에게 터미널을 쥐여주는 도구.
> 가장 강력하고 가장 위험한 도구이므로, 안전 설계가 핵심이다.

---

## 1. 왜 Bash 도구가 필요한가

파일 읽기/쓰기만으로는 에이전트가 할 수 없는 일들이 있다:

- 컴파일: `./gradlew build`
- 테스트 실행: `./gradlew test`
- 패키지 설치: `npm install`
- Git 조작: `git log`, `git diff`
- 프로세스 확인: `ps aux | grep java`
- 네트워크: `curl https://...`

Bash 도구는 에이전트에게 "터미널"을 제공한다.
이것 하나로 파일시스템 이외의 거의 모든 시스템 작업이 가능해진다.

---

## 2. 스키마

```json
{
  "name": "run_bash",
  "description": "Execute a bash command and return its output. Use for running build tools, tests, git commands, file operations that require shell features, or any system command. Prefer specific tools (read_file, list_dir) when available. Commands are executed in the project working directory.",
  "input_schema": {
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "The bash command to execute"
      },
      "timeout": {
        "type": "integer",
        "description": "Timeout in milliseconds. Default 30000 (30s). Long-running commands should increase this.",
        "default": 30000
      },
      "working_dir": {
        "type": "string",
        "description": "Working directory for the command. Defaults to project root."
      }
    },
    "required": ["command"]
  }
}
```

---

## 3. Kotlin 구현

```kotlin
object RunBashTool : ToolExecutor {
    private val DEFAULT_TIMEOUT_MS = 30_000L
    private val MAX_OUTPUT_BYTES = 100_000   // 출력 100KB 제한

    override fun execute(input: JsonObject): String {
        val command = input["command"]?.jsonPrimitive?.content
            ?: return "Error: 'command' is required"
        val timeoutMs = input["timeout"]?.jsonPrimitive?.longOrNull ?: DEFAULT_TIMEOUT_MS
        val workingDir = input["working_dir"]?.jsonPrimitive?.content
            ?: System.getProperty("user.dir")

        // 위험 명령 체크 (Phase 6에서 승인 게이트로 교체)
        checkDangerousCommand(command)?.let { warning ->
            return "Error: $warning\n명령을 실행하려면 명시적으로 확인이 필요합니다."
        }

        return try {
            val process = ProcessBuilder("/bin/bash", "-c", command)
                .directory(File(workingDir))
                .redirectErrorStream(true)  // stderr를 stdout으로 합침
                .start()

            val outputFuture = CompletableFuture.supplyAsync {
                process.inputStream.readNBytes(MAX_OUTPUT_BYTES)
            }

            val finished = process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)

            if (!finished) {
                process.destroyForcibly()
                return "Error: 명령 타임아웃 (${timeoutMs}ms 초과): $command"
            }

            val output = String(outputFuture.get(), Charsets.UTF_8)
            val exitCode = process.exitValue()

            buildString {
                if (exitCode != 0) append("[Exit code: $exitCode]\n")
                append(output.trimEnd())
                if (output.length >= MAX_OUTPUT_BYTES) {
                    append("\n[출력이 ${MAX_OUTPUT_BYTES}바이트에서 잘림]")
                }
            }

        } catch (e: Exception) {
            "Error executing command: ${e.message}"
        }
    }

    private fun checkDangerousCommand(command: String): String? {
        val dangerous = listOf(
            Regex("""rm\s+-rf\s+/""") to "루트 디렉터리 삭제는 허용되지 않습니다",
            Regex(""">\s*/dev/sda""") to "디스크 장치에 직접 쓰기는 허용되지 않습니다",
            Regex(""":()\{.*\}""") to "Fork bomb은 허용되지 않습니다",
            Regex("""dd\s+if=.*of=/dev""") to "디스크 장치 직접 접근은 허용되지 않습니다"
        )
        return dangerous.firstOrNull { (pattern, _) -> pattern.containsMatchIn(command) }?.second
    }
}
```

---

## 4. 명령 실행의 보안 위험

### Command Injection

모델이 생성한 명령이 시스템을 망가뜨릴 수 있다.
`/bin/bash -c command` 방식은 쉘 메타문자(`;`, `|`, `&&`, `` ` ``, `$()`)를 모두 해석하므로,
모델이 악의적이거나 실수로 복합 명령을 만들 수 있다.

```bash
# 모델이 이렇게 쓸 수 있다
rm -rf ./build && rm -rf ~/*
find . -name "*.log" | xargs rm -rf
```

### 대응 전략

1. **화이트리스트**: 허용 명령 목록만 실행
2. **패턴 블락**: 위험 패턴(rm -rf /, dd if=...) 차단
3. **승인 게이트**: 쓰기/삭제 동작 전 사용자 확인 (Phase 6)
4. **Sandbox**: 컨테이너나 가상 환경에서 실행 (고급)

---

## 5. 출력 처리

### stdout과 stderr 합치기

```kotlin
.redirectErrorStream(true)  // stderr → stdout으로 리다이렉트
```

두 스트림을 합치면 모델이 "어떤 에러가 났는지" 한꺼번에 볼 수 있다.
빌드 에러나 컴파일 에러는 보통 stderr로 가므로 합치는 것이 적절하다.

### 출력 크기 제한

컴파일 에러, 로그 파일 출력 등은 수 MB에 달할 수 있다.
100KB 제한을 두고 초과분은 잘라낸다.

```kotlin
// 앞부분보다 뒷부분이 더 중요한 경우 (빌드 오류는 마지막에 나옴)
val output = process.inputStream.readBytes()
val truncated = if (output.size > MAX_OUTPUT_BYTES) {
    // 마지막 MAX_OUTPUT_BYTES만 유지
    "[앞 부분 ${output.size - MAX_OUTPUT_BYTES}바이트 생략]\n" +
    String(output.takeLast(MAX_OUTPUT_BYTES).toByteArray())
} else String(output)
```

### Exit Code 전달

Exit code를 모델에게 알려줘야 성공/실패를 판단할 수 있다:

```
[Exit code: 1]
error: unresolved reference: readFiel
         ^
```

---

## 6. 작업 디렉터리 관리

주의: `ProcessBuilder`로 실행하는 각 명령은 **독립 프로세스**다.
한 명령에서 `cd /other/dir`을 해도 다음 명령의 작업 디렉터리에 영향을 주지 않는다.

```kotlin
// 잘못된 기대
run_bash("cd /tmp")           // 이 cd는 이 프로세스에서만 유효
run_bash("ls")                // 여전히 원래 디렉터리에서 실행됨

// 올바른 방법: 한 명령에서 처리
run_bash("cd /tmp && ls")
// 또는 working_dir 파라미터 사용
run_bash(command="ls", workingDir="/tmp")
```

---

## 7. 장기 실행 명령 처리

```kotlin
// 빌드, 테스트 같은 긴 작업
run_bash(
    command = "./gradlew test",
    timeout = 300_000   // 5분
)

// 백그라운드 실행 (출력 파일로 리다이렉트)
run_bash("./gradlew build > build.log 2>&1 &")
run_bash("tail -20 build.log")  // 나중에 확인
```

---

## 8. 대화형(Interactive) 명령 문제

`vim`, `less`, `ssh`, `python` REPL 같은 대화형 명령은 실행할 수 없다.
이런 명령들은 TTY(터미널)와 사용자 입력을 기다리므로, 우리 ProcessBuilder는 타임아웃된다.

```kotlin
// 대화형 명령 감지
val INTERACTIVE_COMMANDS = listOf("vim", "vi", "nano", "less", "more", "man", "ssh", "python", "python3")

fun isInteractiveCommand(command: String): Boolean {
    val firstWord = command.trim().split(Regex("\\s+")).firstOrNull() ?: return false
    return INTERACTIVE_COMMANDS.any { firstWord == it || firstWord.endsWith("/$it") }
}
```

---

## 9. 유용한 Bash 패턴들

모델이 자주 쓰는 패턴들:

```bash
# 파일 찾기
find . -name "*.kt" -not -path "*/build/*"

# 오류 무시하고 실행
command_that_might_fail || true

# 출력 필터링
./gradlew build 2>&1 | grep -E "^(error|warning|BUILD)"

# JSON 파싱 (jq가 설치된 경우)
curl -s https://api.example.com/data | jq '.items[].name'

# 파일 수정 시간 확인
ls -lt src/main/kotlin/ | head -10

# Git 상태 확인
git log --oneline -10
git diff HEAD~1 HEAD --name-only
```

---

## 10. run_bash와 다른 도구의 관계

`run_bash`는 다른 파일 도구로 할 수 없는 일을 할 때 사용하는 "마지막 수단"이다:

| 작업 | 권장 도구 |
|---|---|
| 파일 내용 보기 | `read_file` |
| 디렉터리 나열 | `list_dir` |
| 문자열 검색 | `grep` |
| 파일 내용 보기 (쉘 기능 필요) | `run_bash("cat ...")` |
| 빌드, 컴파일, 테스트 | `run_bash` |
| Git 조작 | `run_bash` |
| 패키지 관리 | `run_bash` |

---

## References

- [ProcessBuilder Java Documentation](https://docs.oracle.com/javase/8/docs/api/java/lang/ProcessBuilder.html)
- [OWASP Command Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html)
- [Bash Security Best Practices](https://github.com/nicowillis/bash-security)
- [Claude Code run_bash Tool Design](https://docs.anthropic.com/en/docs/claude-code/overview)
