# 룰 (Rules / BOMINI.md)

> **한 줄 요약**: `BOMINI.md` 파일을 읽어서 매 API 호출의 system 프롬프트 앞에
> 자동으로 주입하는 것. 룰의 정체는 "항상 붙는 system 프롬프트 텍스트"다.

---

## 1. 룰이란 무엇인가

에이전트 코어 루프에서 모든 것은 messages 배열(state)에 들어간다.
룰은 **매 API 호출마다 messages 맨 앞에 자동으로 붙는 system 프롬프트**다.

```kotlin
// 룰이 없을 때
client.createMessage(
    messages = state,
    system = null
)

// 룰이 있을 때
val rules = File("BOMINI.md").readText()
client.createMessage(
    messages = state,
    system = rules   // ← 매번 자동으로 주입
)
```

모델은 매 호출마다 이 룰을 읽고, 그 지시에 따라 행동한다.
"마법"이 아니다. 단순히 텍스트를 API 호출에 포함시키는 것이다.

---

## 2. BOMINI.md vs CLAUDE.md

| | CLAUDE.md | BOMINI.md |
|---|---|---|
| 읽는 주체 | Claude Code (개발 도구) | bomini (우리가 만든 앱) |
| 역할 | 개발 가이드 | 앱이 실행 시 로드하는 룰 |
| 위치 | 프로젝트 루트 | 사용자의 작업 디렉터리 |
| 내용 | 코드 스타일, 아키텍처 결정 등 | bomini가 따를 행동 지침 |

```
claude ↔ CLAUDE.md
bomini ↔ BOMINI.md
```

---

## 3. BOMINI.md 예시

```markdown
# 프로젝트 규칙 (BOMINI.md)

## 코드 스타일
- Kotlin 파일은 dev.bomini 패키지를 사용한다
- 클래스명은 PascalCase, 함수명은 camelCase
- 줄 길이 최대 120자

## 작업 규칙
- 파일 수정 전 반드시 read_file로 현재 내용을 확인한다
- 테스트가 존재하면 수정 후 반드시 테스트를 실행한다
- write_file로 파일을 덮어쓰기 전 사용자에게 확인한다

## 금지 사항
- rm -rf / 또는 시스템 파일 삭제 금지
- /etc, ~/.ssh 등 시스템 경로 접근 금지

## 현재 프로젝트 정보
- 빌드: ./gradlew build
- 테스트: ./gradlew test
- 메인 진입점: src/main/kotlin/dev/bomini/Main.kt
```

---

## 4. 룰 로딩 구현

```kotlin
class RulesLoader(
    private val projectDir: String = System.getProperty("user.dir")
) {
    // 룰 파일 탐색 우선순위 (Claude Code와 동일한 구조)
    private val ruleFiles = listOf(
        File(projectDir, "BOMINI.md"),           // 프로젝트 룰
        File(System.getProperty("user.home"), ".bomini/BOMINI.md"), // 글로벌 룰
    )

    fun loadRules(): String? {
        val loadedRules = ruleFiles
            .filter { it.exists() && it.isFile }
            .mapNotNull { file ->
                try {
                    val content = file.readText().trim()
                    if (content.isNotEmpty()) {
                        "=== Rules from ${file.path} ===\n$content"
                    } else null
                } catch (e: Exception) {
                    null
                }
            }
        
        return if (loadedRules.isEmpty()) null
               else loadedRules.joinToString("\n\n")
    }
}

// 에이전트에서 사용
val rulesLoader = RulesLoader()
val systemPrompt = rulesLoader.loadRules()

val response = client.createMessage(
    messages = state,
    tools = tools,
    system = systemPrompt   // 룰 주입
)
```

---

## 5. 룰 탐색 계층 구조

Claude Code는 여러 레벨의 룰 파일을 지원한다:

```
전역 룰: ~/.claude/CLAUDE.md
   └── 프로젝트 룰: /project/CLAUDE.md
         └── 하위 디렉터리 룰: /project/src/CLAUDE.md
```

bomini도 동일한 구조를 구현할 수 있다:

```kotlin
fun loadRulesHierarchical(workingDir: String): String {
    val dirs = mutableListOf<File>()

    // 현재 디렉터리부터 루트까지 올라가며 BOMINI.md 탐색
    var dir = File(workingDir)
    while (dir.parentFile != null) {
        dirs.add(dir)
        dir = dir.parentFile!!
    }

    // 글로벌 룰 추가
    dirs.add(File(System.getProperty("user.home"), ".bomini"))

    // 위(글로벌)에서 아래(로컬)로 쌓기 (로컬이 더 우선)
    return dirs.reversed()
        .mapNotNull { d -> File(d, "BOMINI.md").takeIf { it.exists() } }
        .mapNotNull { it.readTextOrNull() }
        .joinToString("\n\n---\n\n")
}
```

---

## 6. 룰과 토큰 비용

룰은 매 API 호출마다 system 프롬프트에 포함된다.
룰이 길면 그만큼 매 호출의 입력 토큰이 늘어나고 비용이 증가한다.

```
룰 파일 크기와 비용 관계:
- 룰 없음: baseline
- 룰 1,000 토큰 (2~3페이지): +$0.003/호출 (Sonnet 기준)
- 룰 10,000 토큰 (20페이지): +$0.03/호출

세션에서 50번 호출 시:
- 1,000 토큰 룰: +$0.15
- 10,000 토큰 룰: +$1.50
```

**실용적 권장**: 룰은 핵심적인 지침만 담고 간결하게 유지한다.
상세 문서는 스킬(skills) 파일로 분리한다.

---

## 7. 동적 룰 (컨텍스트 감지)

프로젝트 타입에 따라 다른 룰을 자동으로 선택:

```kotlin
fun loadContextualRules(workingDir: String): String {
    val baseRules = loadRules()

    // 프로젝트 타입 감지
    val additionalRules = when {
        File(workingDir, "build.gradle.kts").exists() -> loadKotlinRules()
        File(workingDir, "package.json").exists() -> loadNodeRules()
        File(workingDir, "Cargo.toml").exists() -> loadRustRules()
        File(workingDir, "requirements.txt").exists() -> loadPythonRules()
        else -> ""
    }

    return listOfNotNull(baseRules, additionalRules)
        .filter { it.isNotBlank() }
        .joinToString("\n\n")
}
```

---

## 8. 룰 디버깅

룰이 제대로 적용되는지 확인하려면:

```bash
# bomini 실행 시 적용된 system 프롬프트 출력
bomini --show-system-prompt

# 출력:
# === Applied System Prompt ===
# === Rules from /project/BOMINI.md ===
# # 프로젝트 규칙
# ...
```

```kotlin
// 개발 중 디버깅
if (debugMode) {
    println("=== System Prompt ===")
    println(systemPrompt ?: "(none)")
    println("====================")
}
```

---

## 9. 룰의 한계

- **모델이 룰을 어길 수 있다**: 룰은 지시일 뿐, 강제 실행 메커니즘이 아니다.
  모델이 확률적으로 룰을 무시하거나 잘못 해석할 수 있다.
- **긴 룰은 무시될 수 있다**: "Lost in the Middle" 현상 — 긴 context 중간의 내용은
  모델이 덜 주의를 기울이는 경향이 있다.
- **룰 충돌**: 여러 룰 파일이 서로 충돌하는 지시를 담을 수 있다.

실제 안전 강제는 승인 게이트(approval gate)로 구현해야 한다.

---

## References

- [Claude Code CLAUDE.md Documentation](https://docs.anthropic.com/en/docs/claude-code/memory)
- [System Prompts Best Practices (Anthropic)](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/system-prompts)
- [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172)
- [Prompt Injection Attacks on LLMs](https://arxiv.org/abs/2302.12173)
