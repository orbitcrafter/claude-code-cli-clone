# 파일 도구 (read_file / write_file / edit_file / list_dir)

> **한 줄 요약**: 에이전트가 파일시스템을 조작하는 4개의 기본 도구.
> read/list는 관찰, write는 생성, edit는 정밀 수정이다.

---

## 1. 왜 파일 도구가 핵심인가

코딩 에이전트의 작업 대부분은 파일을 읽고, 수정하고, 새로 만드는 것이다.
이 4개 도구만 있어도 "코드 파일을 보고 → 수정을 결정하고 → 실제로 바꾸는" 사이클이 완성된다.

```
list_dir(".")          → 어떤 파일이 있는지 파악
read_file("src/A.kt")  → 내용 확인
edit_file(...)         → 수정
read_file("src/A.kt")  → 수정 결과 확인
```

---

## 2. read_file

### 목적

파일의 내용을 읽어서 모델에게 보여준다.
모델이 코드를 이해하고, 설정을 확인하고, 문서를 읽는 모든 경우에 사용된다.

### 스키마

```json
{
  "name": "read_file",
  "description": "Read the complete contents of a file from the filesystem. Use this when you need to examine file contents, understand code structure, check configuration, or read documentation.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute or relative path to the file"
      },
      "offset": {
        "type": "integer",
        "description": "Line number to start reading from (0-indexed). Use for large files."
      },
      "limit": {
        "type": "integer",
        "description": "Maximum number of lines to read. Defaults to 2000."
      }
    },
    "required": ["path"]
  }
}
```

### Kotlin 구현

```kotlin
object ReadFileTool : ToolExecutor {
    override fun execute(input: JsonObject): String {
        val path = input["path"]?.jsonPrimitive?.content
            ?: return "Error: 'path' is required"
        
        val offset = input["offset"]?.jsonPrimitive?.intOrNull ?: 0
        val limit = input["limit"]?.jsonPrimitive?.intOrNull ?: 2000
        
        val file = File(path)
        if (!file.exists()) return "Error: File not found: $path"
        if (!file.isFile) return "Error: Not a file: $path"
        
        val lines = file.readLines()
        val totalLines = lines.size
        val selected = lines.drop(offset).take(limit)
        
        // 줄 번호 포함 (Claude Code 방식: "1\t내용")
        val numbered = selected.mapIndexed { i, line ->
            "${offset + i + 1}\t$line"
        }.joinToString("\n")
        
        val truncated = offset + limit < totalLines
        val footer = if (truncated) 
            "\n[파일 총 $totalLines 줄 중 ${offset+1}~${offset+limit} 줄 표시. 나머지는 offset=${offset+limit}으로 조회]"
        else ""
        
        return numbered + footer
    }
}
```

### 중요 설계 결정: 줄 번호 포함

줄 번호를 포함해서 반환하면:
- 모델이 "12번째 줄을 수정하라"고 참조할 수 있다
- edit_file에서 정확한 위치를 지정할 수 있다
- 큰 파일에서 offset 기반 페이징이 가능하다

---

## 3. write_file

### 목적

새 파일을 생성하거나 기존 파일의 전체 내용을 덮어쓴다.
새 파일 생성, 설정 파일 작성, 테스트 파일 생성 등에 사용된다.

### 스키마

```json
{
  "name": "write_file",
  "description": "Write content to a file, creating it if it doesn't exist or overwriting if it does. Use for creating new files or completely replacing file contents. For modifying specific parts of an existing file, use edit_file instead.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Path to the file to write"
      },
      "content": {
        "type": "string",
        "description": "The content to write to the file"
      }
    },
    "required": ["path", "content"]
  }
}
```

### Kotlin 구현

```kotlin
object WriteFileTool : ToolExecutor {
    override fun execute(input: JsonObject): String {
        val path = input["path"]?.jsonPrimitive?.content
            ?: return "Error: 'path' is required"
        val content = input["content"]?.jsonPrimitive?.content
            ?: return "Error: 'content' is required"
        
        val file = File(path)
        
        // 안전장치: 기존 파일 덮어쓰기는 확인 필요 (Phase 6에서 승인 게이트와 연결)
        val isOverwrite = file.exists()
        
        // 부모 디렉터리 자동 생성
        file.parentFile?.mkdirs()
        
        file.writeText(content)
        
        return if (isOverwrite)
            "파일 덮어쓰기 완료: $path (${content.lines().size} 줄)"
        else
            "파일 생성 완료: $path (${content.lines().size} 줄)"
    }
}
```

### 주의: write_file은 파괴적 연산이다

기존 파일을 통째로 덮어쓰므로, 실수로 큰 파일의 일부만 작성하면 나머지 내용이 사라진다.
**Phase 6에서 write_file에 승인 게이트를 붙인다.**

---

## 4. edit_file (정밀 편집)

### 목적

파일 전체를 덮어쓰지 않고, 특정 부분만 정밀하게 수정한다.
`old_string → new_string` 치환 방식으로 동작한다.

이것이 Claude Code의 `Edit` 도구의 핵심이다.

### 스키마

```json
{
  "name": "edit_file",
  "description": "Make precise edits to a file by replacing specific text. Finds the exact old_string in the file and replaces it with new_string. The old_string must match exactly (including whitespace and indentation). Use read_file first to see the exact content.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Path to the file to edit"
      },
      "old_string": {
        "type": "string",
        "description": "The exact text to find and replace. Must match exactly."
      },
      "new_string": {
        "type": "string",
        "description": "The new text to replace old_string with"
      },
      "replace_all": {
        "type": "boolean",
        "description": "If true, replace all occurrences. Default is false (only first occurrence)."
      }
    },
    "required": ["path", "old_string", "new_string"]
  }
}
```

### Kotlin 구현

```kotlin
object EditFileTool : ToolExecutor {
    override fun execute(input: JsonObject): String {
        val path = input["path"]?.jsonPrimitive?.content
            ?: return "Error: 'path' is required"
        val oldString = input["old_string"]?.jsonPrimitive?.content
            ?: return "Error: 'old_string' is required"
        val newString = input["new_string"]?.jsonPrimitive?.content
            ?: return "Error: 'new_string' is required"
        val replaceAll = input["replace_all"]?.jsonPrimitive?.booleanOrNull ?: false
        
        val file = File(path)
        if (!file.exists()) return "Error: File not found: $path"
        
        val content = file.readText()
        
        // 정확한 매치 확인
        if (!content.contains(oldString)) {
            return """Error: old_string not found in $path.
                |The text must match exactly (including whitespace and indentation).
                |Use read_file to see the exact content first.""".trimMargin()
        }
        
        // 중복 경고 (replace_all이 false인데 여러 개 발견)
        val occurrences = content.split(oldString).size - 1
        if (occurrences > 1 && !replaceAll) {
            return """Error: old_string found $occurrences times in $path.
                |Provide a larger old_string with more context to make it unique,
                |or set replace_all=true to replace all occurrences.""".trimMargin()
        }
        
        val newContent = if (replaceAll)
            content.replace(oldString, newString)
        else
            content.replaceFirst(oldString, newString)
        
        file.writeText(newContent)
        return "편집 완료: $path (${occurrences}개 치환)"
    }
}
```

### edit_file의 핵심 설계 원칙

1. **정확 일치(exact match)**: old_string은 파일에 있는 내용과 공백 하나까지 동일해야 한다.
   이것이 의도치 않은 부분 수정을 방지한다.

2. **중복 차단**: old_string이 파일에 여러 번 등장하면 에러를 반환한다.
   어느 것을 바꿔야 하는지 모델이 맥락을 더 제공하도록 강제한다.

3. **read_file 선행**: 모델이 edit_file을 쓰기 전에 반드시 read_file로 내용을 확인해야 한다.
   그래야 정확한 old_string을 알 수 있다.

---

## 5. list_dir

### 목적

디렉터리의 파일과 하위 디렉터리 목록을 보여준다.
에이전트가 "무엇이 있는지" 파악하기 위한 첫 번째 단계다.

### 스키마

```json
{
  "name": "list_dir",
  "description": "List files and directories at the given path. Shows file names, types, and sizes. Use to explore the project structure before reading files.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Directory path to list"
      },
      "recursive": {
        "type": "boolean",
        "description": "If true, recursively list subdirectories. Default false."
      }
    },
    "required": ["path"]
  }
}
```

### Kotlin 구현

```kotlin
object ListDirTool : ToolExecutor {
    override fun execute(input: JsonObject): String {
        val path = input["path"]?.jsonPrimitive?.content
            ?: return "Error: 'path' is required"
        val recursive = input["recursive"]?.jsonPrimitive?.booleanOrNull ?: false
        
        val dir = File(path)
        if (!dir.exists()) return "Error: Directory not found: $path"
        if (!dir.isDirectory) return "Error: Not a directory: $path"
        
        return buildString {
            listEntries(dir, "", recursive, this)
        }
    }

    private fun listEntries(
        dir: File,
        prefix: String,
        recursive: Boolean,
        sb: StringBuilder
    ) {
        val entries = dir.listFiles()
            ?.sortedWith(compareBy({ !it.isDirectory }, { it.name }))
            ?: return

        entries.forEach { entry ->
            val indicator = if (entry.isDirectory) "/" else ""
            val size = if (entry.isFile) " (${formatSize(entry.length())})" else ""
            sb.appendLine("$prefix${entry.name}$indicator$size")
            
            if (recursive && entry.isDirectory) {
                listEntries(entry, "$prefix  ", true, sb)
            }
        }
    }

    private fun formatSize(bytes: Long): String = when {
        bytes < 1024 -> "${bytes}B"
        bytes < 1024 * 1024 -> "${bytes / 1024}KB"
        else -> "${bytes / (1024 * 1024)}MB"
    }
}
```

---

## 6. 파일 도구 사용 패턴

### 패턴 1: 탐색 → 읽기 → 수정

```
list_dir(".")
  → read_file("src/main.kt")
  → edit_file(path="src/main.kt", old="val x = 1", new="val x = 2")
  → read_file("src/main.kt")    ← 수정 확인
```

### 패턴 2: 새 파일 생성

```
list_dir("src/")              ← 기존 파일 확인
  → write_file("src/new.kt", "package dev.bomini\n...")
  → read_file("src/new.kt")   ← 생성 확인
```

### 패턴 3: 여러 파일 동시 읽기 (병렬)

```
read_file("A.kt") + read_file("B.kt")   ← 모델이 두 tool_use를 한 번에 요청
  → [병렬 실행]
  → 두 결과를 한꺼번에 state에 주입
```

---

## 7. 보안 고려사항

### Path Traversal 방지

```kotlin
fun sanitizePath(path: String, workingDir: String): String {
    val resolved = File(workingDir).resolve(path).canonicalPath
    if (!resolved.startsWith(File(workingDir).canonicalPath)) {
        throw SecurityException("Path traversal detected: $path")
    }
    return resolved
}
```

### 위험 파일 보호

```kotlin
val PROTECTED_PATHS = setOf(
    "/etc/passwd", "/etc/shadow",
    "~/.ssh", "~/.aws/credentials"
)

fun isProtectedPath(path: String): Boolean {
    return PROTECTED_PATHS.any { path.startsWith(it) }
}
```

---

## References

- [Anthropic Tool Use — File Reading Pattern](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [Claude Code Edit Tool Documentation](https://docs.anthropic.com/en/docs/claude-code/overview)
- [OWASP Path Traversal Prevention](https://owasp.org/www-community/attacks/Path_Traversal)
- [Java File API (Kotlin 파일 처리)](https://kotlinlang.org/api/latest/jvm/stdlib/kotlin.io/)
