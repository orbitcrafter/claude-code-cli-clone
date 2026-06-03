# 세션 영속화 (Session Persistence)

> **한 줄 요약**: state(누적 메시지 배열)를 디스크에 저장해서, 나중에 이어서 대화할 수 있게 하는 것.
> 세션의 정체는 state의 스냅샷이다.

---

## 1. 세션이란 무엇인가

에이전트 코어 루프에서 `state`는 메시지 배열이다:

```kotlin
val state = mutableListOf<Message>(
    Message(role="user", content=[Text("Kotlin 파일 만들어줘")]),
    Message(role="assistant", content=[ToolUse("list_dir", ...)]),
    Message(role="user", content=[ToolResult("README.md\nsrc/")]),
    Message(role="assistant", content=[ToolUse("write_file", ...)]),
    Message(role="user", content=[ToolResult("파일 생성 완료")]),
    Message(role="assistant", content=[Text("Main.kt를 생성했습니다.")]),
    // ...계속 쌓임
)
```

이 배열을 **세션**이라고 부른다.
세션 영속화(session persistence)는 이 배열을 JSON으로 직렬화해서 파일에 저장하고,
나중에 불러와서 대화를 이어가는 것이다.

---

## 2. 세션의 구성 요소

```kotlin
@Serializable
data class Session(
    val id: String,                  // 고유 식별자 (UUID)
    val createdAt: Long,             // 생성 시각 (epoch ms)
    val updatedAt: Long,             // 마지막 업데이트
    val title: String,               // 세션 요약 제목 (자동 생성 or 사용자 지정)
    val model: String,               // 현재 사용 중인 모델
    val workingDir: String,          // 작업 디렉터리
    val messages: List<Message>,     // 전체 대화 이력 (= state)
    val tokenCount: Int = 0          // 대략적인 토큰 수
)
```

---

## 3. 저장 포맷 (JSON)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "createdAt": 1717200000000,
  "updatedAt": 1717203600000,
  "title": "Kotlin 파일 구조 만들기",
  "model": "claude-sonnet-4-6",
  "workingDir": "/Users/dev/my-project",
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "Kotlin 파일 만들어줘" }
      ]
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "tool_use",
          "id": "toolu_01...",
          "name": "write_file",
          "input": { "path": "Main.kt", "content": "fun main() {}" }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_01...",
          "content": "파일 생성 완료: Main.kt"
        }
      ]
    }
  ],
  "tokenCount": 1547
}
```

---

## 4. 파일 시스템 구조

```
~/.bomini/
  sessions/
    550e8400.json          # 세션 ID = 파일명
    7c9e6679.json
    3f2504e0.json
  config.json              # API 키 등 설정
```

---

## 5. Kotlin 구현

### 세션 매니저

```kotlin
class SessionManager(
    private val sessionsDir: File = File(
        System.getProperty("user.home"), ".bomini/sessions"
    )
) {
    init {
        sessionsDir.mkdirs()
    }

    // 새 세션 생성
    fun createSession(workingDir: String, model: String): Session {
        val session = Session(
            id = UUID.randomUUID().toString(),
            createdAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis(),
            title = "새 세션",
            model = model,
            workingDir = workingDir,
            messages = emptyList()
        )
        save(session)
        return session
    }

    // 세션 저장
    fun save(session: Session) {
        val file = File(sessionsDir, "${session.id}.json")
        file.writeText(
            Json { prettyPrint = true }.encodeToString(session.copy(
                updatedAt = System.currentTimeMillis()
            ))
        )
    }

    // 세션 불러오기
    fun load(sessionId: String): Session? {
        val file = File(sessionsDir, "$sessionId.json")
        if (!file.exists()) return null
        return try {
            Json { ignoreUnknownKeys = true }.decodeFromString<Session>(file.readText())
        } catch (e: Exception) {
            null   // 손상된 세션 파일 무시
        }
    }

    // 세션 목록 (최근 수정순)
    fun listSessions(): List<Session> {
        return sessionsDir.listFiles { f -> f.extension == "json" }
            ?.mapNotNull { file ->
                try {
                    Json { ignoreUnknownKeys = true }.decodeFromString<Session>(file.readText())
                } catch (e: Exception) {
                    null
                }
            }
            ?.sortedByDescending { it.updatedAt }
            ?: emptyList()
    }

    // 세션 삭제
    fun delete(sessionId: String): Boolean {
        return File(sessionsDir, "$sessionId.json").delete()
    }
}
```

### 세션 이어가기

```kotlin
suspend fun main() {
    val sessionManager = SessionManager()

    // 기존 세션 선택 또는 새 세션 생성
    val session = when {
        args.contains("--resume") -> {
            val sessions = sessionManager.listSessions()
            if (sessions.isEmpty()) {
                sessionManager.createSession(workingDir, defaultModel)
            } else {
                // 가장 최근 세션 이어가기
                sessions.first()
            }
        }
        else -> sessionManager.createSession(workingDir, defaultModel)
    }

    // state 복원
    val state = session.messages.toMutableList()

    // 에이전트 루프 실행 (state는 이미 이전 대화를 포함)
    runAgentLoop(state, session)
}
```

---

## 6. 자동 저장 전략

매 턴마다 저장하면 안전하지만 I/O가 많아진다:

```kotlin
// 전략 1: 매 어시스턴트 응답마다 저장 (권장)
suspend fun agent(session: Session, userMessage: String) {
    session.messages.add(Message.user(userMessage))
    sessionManager.save(session)   // 저장

    while (true) {
        val response = client.createMessage(session.messages, tools)
        session.messages.add(response.toMessage())
        sessionManager.save(session)   // 응답 후 저장

        val toolUses = response.toolUses
        if (toolUses.isEmpty()) break

        val results = toolUses.map { runTool(it) }
        session.messages.add(Message.toolResults(results))
        sessionManager.save(session)   // 도구 결과 후 저장
    }
}

// 전략 2: 사용자 입력마다만 저장 (가벼운 방식)
// 중간에 앱이 죽으면 마지막 사용자 입력은 잃지만, 이전 내용은 보존
```

---

## 7. 세션 제목 자동 생성

첫 번째 사용자 메시지에서 제목을 자동 생성:

```kotlin
fun generateTitle(firstMessage: String): String {
    return firstMessage.take(50).let { text ->
        if (text.length < firstMessage.length) "$text..." else text
    }
}

// 또는 모델에게 요약시키기 (비용 발생)
suspend fun generateTitleWithModel(firstMessage: String): String {
    val response = client.createMessage(
        messages = listOf(
            Message.user("다음 작업의 제목을 10자 이내로 만들어줘: $firstMessage")
        ),
        tools = emptyList(),
        model = ClaudeModel.HAIKU_4.id  // 저렴한 모델 사용
    )
    return response.textContent ?: generateTitle(firstMessage)
}
```

---

## 8. 세션 목록 UI

```
bomini --list

ID       제목                          모델       업데이트
─────────────────────────────────────────────────────────
550e8400  Kotlin 파일 구조 만들기       Sonnet 4   2분 전
7c9e6679  build.gradle.kts 설정        Haiku 4    1시간 전
3f2504e0  API 클라이언트 구현           Sonnet 4   어제
```

---

## 9. 세션과 컨텍스트 윈도우의 관계

세션이 길어지면 messages 배열이 커지고, 이것이 context window를 채운다.

```
세션 길이 (메시지 수)
     ↑
     │          ┌─────────────────────┐  context window 한계
     │          │   DANGER ZONE       │
     │      ────┤                     │
     │          │                     │
     │          │  정상 영역           │
     │          │                     │
     └──────────┴─────────────────────→ 토큰 수
```

이것이 **compaction**(다음 문서)이 필요한 이유다.
세션 저장은 "파일 저장"이고, compaction은 "context 압축"이다.

---

## 10. 세션 마이그레이션

포맷이 바뀌면 구 형식 세션을 읽지 못할 수 있다:

```kotlin
@Serializable
data class Session(
    val version: Int = 1,    // 포맷 버전
    // ...
)

fun loadWithMigration(file: File): Session {
    val raw = Json.parseToJsonElement(file.readText()).jsonObject
    return when (raw["version"]?.jsonPrimitive?.intOrNull ?: 1) {
        1 -> migrateV1ToV2(Json.decodeFromJsonElement<SessionV1>(raw))
        2 -> Json.decodeFromJsonElement<Session>(raw)
        else -> throw IllegalStateException("Unknown session version")
    }
}
```

---

## References

- [Anthropic Context Window Documentation](https://docs.anthropic.com/en/docs/about-claude/models)
- [kotlinx.serialization JSON](https://kotlinlang.org/docs/serialization.html)
- [UUID v4 Generation (Java)](https://docs.oracle.com/javase/8/docs/api/java/util/UUID.html)
- [Claude Code Session Management](https://docs.anthropic.com/en/docs/claude-code/memory)
