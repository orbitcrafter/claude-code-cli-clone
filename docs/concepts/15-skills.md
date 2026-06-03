# 스킬 (Skills)

> **한 줄 요약**: TOOLS 목록에 "description + 파일 경로" 항목을 추가하는 것.
> 모델이 description을 보고 그 파일을 읽어야 한다고 판단할 때 호출한다.
> **호출 여부는 결정론이 아니라 모델의 확률적 판단이다.**

---

## 1. 스킬의 정체

스킬(skill)은 결국 도구(tool)다.
차이는 하나뿐이다: **"실행"이 아니라 "읽기"를 수행한다.**

```
일반 도구: name + description + 실행 코드
스킬:      name + description + "이 파일을 읽어라"
```

```kotlin
// 일반 도구
val BASH_TOOL = Tool(
    name = "run_bash",
    description = "Execute shell commands",
    // → run_bash 함수 실행
)

// 스킬 도구
val COMMIT_SKILL = Tool(
    name = "smart_commit",
    description = "Guides for analyzing git changes and creating meaningful, 
                  atomic commits. Use when asked to commit changes.",
    // → skills/smart-commit.md 파일 읽기
)
```

---

## 2. 왜 스킬이 필요한가

모든 가이드를 system 프롬프트에 넣으면:
```
system: "커밋 가이드: ... 100줄 ...
         코드리뷰 가이드: ... 200줄 ...
         API 사용 가이드: ... 300줄 ...
         ..." → 매 호출마다 토큰 낭비
```

스킬은 **필요할 때만** 가이드를 로드한다:
```
system: (최소한의 내용)
tools: [
  { name: "commit_guide", description: "Use when committing" },
  { name: "review_guide", description: "Use when reviewing code" }
]

→ 모델이 커밋 관련 작업을 할 때만 commit_guide 읽기
→ 코드 리뷰를 할 때만 review_guide 읽기
```

---

## 3. 스킬 파일 구조

```
/skills
  smart-commit.md          ← 스킬 가이드 파일
  code-review.md
  security-review.md
  memo-writer.md
```

스킬 파일은 단순한 마크다운 문서다:

```markdown
# Smart Commit 가이드

## 언제 사용하는가
사용자가 "커밋해줘", "git commit", "변경사항 커밋" 등을 요청할 때.

## 절차

### 1. 변경사항 분석
먼저 다음을 실행하여 전체 변경사항을 파악한다:
- `git status` — 변경된 파일 목록
- `git diff` — 변경 내용 상세
- `git log --oneline -5` — 최근 커밋 스타일 참고

### 2. 의미있는 단위로 분류
...
```

---

## 4. 스킬 도구 구현

```kotlin
// 스킬 파일을 읽어서 반환하는 도구 생성
fun createSkillTool(
    name: String,
    description: String,
    skillFile: File
): ToolExecutor {
    return object : ToolExecutor {
        override val definition = Tool(
            name = name,
            description = description,
            inputSchema = ToolInputSchema(
                properties = mapOf(
                    "args" to PropertySchema(
                        "string",
                        "Optional additional context or arguments"
                    )
                ),
                required = emptyList()
            )
        )

        override fun execute(input: JsonObject): String {
            if (!skillFile.exists()) {
                return "Error: Skill file not found: ${skillFile.path}"
            }
            
            val args = input["args"]?.jsonPrimitive?.content
            val content = skillFile.readText()
            
            return if (args != null) {
                "$content\n\n[Additional context: $args]"
            } else {
                content
            }
        }
    }
}

// 사용
val smartCommitSkill = createSkillTool(
    name = "smart_commit",
    description = """Guides for creating meaningful git commits.
        Use when user asks to commit, 'git commit', or mentions committing changes.
        Returns step-by-step commit creation guide.""",
    skillFile = File("skills/smart-commit.md")
)
```

---

## 5. 호출률의 비결정성 (핵심 학습 포인트)

이것이 이 프로젝트의 출발점이 된 원래 질문이다:
**"스킬이 왜 어떨 땐 호출되고 어떨 땐 안 되나?"**

### 모델은 확률적으로 판단한다

같은 사용자 입력에도 스킬 호출 여부가 달라질 수 있다.

```
사용자: "커밋해줘"

경우 A: 모델이 smart_commit 스킬을 호출
→ "smart-commit.md를 읽겠습니다..." → 가이드 로드 → 절차 따름

경우 B: 모델이 스킬 없이 바로 실행
→ "git add . && git commit -m '...' " 바로 실행

두 경우 모두 발생 가능. 어떤 경우가 일어날지 사전에 결정할 수 없다.
```

### Description이 호출률을 결정한다

description 문구에 따라 모델의 호출 확률이 달라진다:

```kotlin
// 낮은 호출률 — 너무 모호함
description = "Commit guide"

// 높은 호출률 — 트리거 조건이 명확함
description = """Step-by-step guide for creating git commits.
    ALWAYS use this when the user asks to commit, mentions 'git commit',
    or asks to save/push changes to git."""

// 과도하게 높은 호출률 — 오히려 문제
description = """MUST USE THIS TOOL ALWAYS FOR EVERYTHING RELATED TO GIT."""
```

### 실험: description을 바꿔가며 호출률 관찰

Phase 2에서 해볼 실험:

```kotlin
// 실험 1: 트리거 단어 없음
val v1 = createSkillTool("commit_guide", "Commit documentation", ...)

// 실험 2: 트리거 단어 명확
val v2 = createSkillTool("commit_guide", 
    "Use when creating git commits or when user says 'commit'", ...)

// 실험 3: 강제 트리거
val v3 = createSkillTool("commit_guide",
    "ALWAYS use this before any git commit operation", ...)

// 각각으로 20번씩 테스트:
// "커밋해줘" → v1은 5/20, v2는 15/20, v3는 18/20 호출
```

---

## 6. Claude Code의 스킬 시스템

Claude Code에서 스킬은 `.claude/commands/` 디렉터리의 마크다운 파일이다:

```
.claude/
  commands/
    smart-commit.md   → /smart-commit 슬래시 커맨드
    code-review.md    → /code-review 슬래시 커맨드
```

사용자가 `/smart-commit`을 입력하면 그 파일이 로드되어 모델에게 전달된다.
bomini의 스킬은 이것을 "도구로 래핑"한 버전이다.

---

## 7. 스킬 레지스트리

```kotlin
class SkillRegistry(private val skillsDir: File = File("skills")) {
    fun loadAllSkills(): List<ToolExecutor> {
        if (!skillsDir.exists()) return emptyList()
        
        return skillsDir.listFiles { f -> f.extension == "md" }
            ?.mapNotNull { file ->
                parseSkillMetadata(file)?.let { meta ->
                    createSkillTool(
                        name = meta.name,
                        description = meta.description,
                        skillFile = file
                    )
                }
            } ?: emptyList()
    }
    
    private fun parseSkillMetadata(file: File): SkillMeta? {
        // 파일 상단 frontmatter 파싱
        // ---
        // name: smart_commit
        // description: "..."
        // ---
        val content = file.readText()
        val frontmatter = Regex("""^---\n(.*?)\n---""", RegexOption.DOT_MATCHES_ALL)
            .find(content)?.groupValues?.get(1) ?: return null
        
        val name = Regex("""name:\s*(.+)""").find(frontmatter)?.groupValues?.get(1)?.trim()
            ?: file.nameWithoutExtension.replace("-", "_")
        val description = Regex("""description:\s*"(.+?)"""").find(frontmatter)?.groupValues?.get(1)?.trim()
            ?: return null
        
        return SkillMeta(name, description)
    }
}

data class SkillMeta(val name: String, val description: String)
```

---

## 8. 스킬 파일 예시 (완전한 포맷)

```markdown
---
name: smart_commit
description: "Step-by-step git commit guide. Use when user asks to commit, 
             mentions 'git commit', '커밋해줘', or wants to save changes."
triggers:
  - "commit"
  - "커밋"
  - "git add"
---

# Smart Commit 가이드

이 스킬은 변경사항을 분석하여 의미있는 커밋을 만드는 절차를 안내합니다.

## 1단계: 현재 상태 파악

다음 명령을 실행하세요:
...
```

---

## References

- [Claude Code Custom Slash Commands](https://docs.anthropic.com/en/docs/claude-code/slash-commands)
- [Claude Code Memory and Skills](https://docs.anthropic.com/en/docs/claude-code/memory)
- [Prompt Engineering for Tool Selection (Anthropic)](https://docs.anthropic.com/en/docs/build-with-claude/tool-use#best-practices-for-tool-definitions)
- [Few-Shot Prompting — Tool Description Quality](https://arxiv.org/abs/2005.14165)
