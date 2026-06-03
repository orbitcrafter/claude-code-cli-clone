# 검색 도구 (grep / search)

> **한 줄 요약**: 코드베이스에서 패턴이나 키워드를 빠르게 찾는 도구.
> "어디에 있는지 모를 때" 먼저 검색하고, 찾은 뒤 read_file한다.

---

## 1. 왜 검색 도구가 필요한가

코드베이스에는 수백~수천 개의 파일이 있을 수 있다.
모델이 "UserService가 어디 있지?"를 알려면 두 가지 방법이 있다:

1. **무식한 방법**: 모든 파일을 read_file → 엄청난 context 낭비, 느림
2. **스마트한 방법**: grep으로 먼저 위치를 찾고 → 해당 파일만 read_file

grep은 대규모 코드베이스에서 에이전트의 탐색 비용을 수십 배 줄여준다.

---

## 2. grep 도구

### 스키마

```json
{
  "name": "grep",
  "description": "Search for a pattern in files using regular expressions. Returns matching lines with file paths and line numbers. Use this to find function definitions, class usages, TODO comments, or any text pattern across the codebase.",
  "input_schema": {
    "type": "object",
    "properties": {
      "pattern": {
        "type": "string",
        "description": "Regular expression or literal string to search for"
      },
      "path": {
        "type": "string",
        "description": "Directory or file to search in. Defaults to current directory."
      },
      "include": {
        "type": "string",
        "description": "File pattern to include (e.g., '*.kt', '*.json')"
      },
      "exclude": {
        "type": "string",
        "description": "File pattern to exclude (e.g., '*/build/*')"
      },
      "case_insensitive": {
        "type": "boolean",
        "description": "Ignore case when matching. Default false."
      },
      "max_results": {
        "type": "integer",
        "description": "Maximum number of results to return. Default 50."
      }
    },
    "required": ["pattern"]
  }
}
```

### Kotlin 구현

```kotlin
object GrepTool : ToolExecutor {
    private val MAX_RESULTS = 50

    override fun execute(input: JsonObject): String {
        val pattern = input["pattern"]?.jsonPrimitive?.content
            ?: return "Error: 'pattern' is required"
        val path = input["path"]?.jsonPrimitive?.content ?: "."
        val include = input["include"]?.jsonPrimitive?.content
        val exclude = input["exclude"]?.jsonPrimitive?.content
        val caseInsensitive = input["case_insensitive"]?.jsonPrimitive?.booleanOrNull ?: false
        val maxResults = input["max_results"]?.jsonPrimitive?.intOrNull ?: MAX_RESULTS

        val flags = if (caseInsensitive) RegexOption.IGNORE_CASE else null
        val regex = try {
            if (flags != null) Regex(pattern, flags) else Regex(pattern)
        } catch (e: Exception) {
            return "Error: Invalid regex pattern: ${e.message}"
        }

        val results = mutableListOf<String>()
        val startDir = File(path)
        
        if (!startDir.exists()) return "Error: Path not found: $path"

        searchDir(startDir, regex, include, exclude, results, maxResults)

        return if (results.isEmpty()) {
            "No matches found for pattern: $pattern"
        } else {
            val truncated = results.size >= maxResults
            results.joinToString("\n") + 
            if (truncated) "\n[결과 ${maxResults}개에서 중단. 더 구체적인 패턴을 사용하세요]" else ""
        }
    }

    private fun searchDir(
        dir: File,
        regex: Regex,
        include: String?,
        exclude: String?,
        results: MutableList<String>,
        maxResults: Int
    ) {
        if (results.size >= maxResults) return

        dir.walkTopDown()
            .filter { it.isFile }
            .filter { file ->
                // 바이너리 파일, 빌드 디렉터리 제외
                !isBinaryFile(file) &&
                !isExcludedPath(file.path) &&
                (include == null || matchesGlob(file.name, include)) &&
                (exclude == null || !matchesGlob(file.path, exclude))
            }
            .forEach { file ->
                if (results.size >= maxResults) return@forEach
                
                file.forEachIndexed { lineNum, line ->
                    if (results.size >= maxResults) return@forEachIndexed
                    if (regex.containsMatchIn(line)) {
                        results.add("${file.path}:${lineNum + 1}: $line")
                    }
                }
            }
    }

    private fun isExcludedPath(path: String): Boolean {
        return path.contains("/build/") ||
               path.contains("/.git/") ||
               path.contains("/node_modules/") ||
               path.contains("/.gradle/")
    }

    private fun isBinaryFile(file: File): Boolean {
        val binaryExtensions = setOf("class", "jar", "zip", "png", "jpg", "gif", "pdf", "exe")
        return file.extension.lowercase() in binaryExtensions
    }
}

// File extension helper
private fun File.forEachIndexed(action: (Int, String) -> Unit) {
    var i = 0
    forEachLine { line -> action(i++, line) }
}
```

### 출력 포맷

```
src/main/kotlin/dev/bomini/core/Agent.kt:23: suspend fun agent(
src/main/kotlin/dev/bomini/core/Agent.kt:47:     val response = client.createMessage(
src/main/kotlin/dev/bomini/tools/RunBash.kt:12: object RunBashTool : ToolExecutor {
```

`파일경로:줄번호: 내용` 형식으로 반환하면 모델이 `read_file(path, offset=23)`으로 바로 이동할 수 있다.

---

## 3. ripgrep 활용 (run_bash 통해)

실제 프로덕션에서는 자체 grep 구현보다 **ripgrep(rg)**를 `run_bash`로 호출하는 것이 훨씬 빠르다:

```kotlin
// ripgrep을 run_bash로 활용
run_bash("rg 'fun agent' --type kotlin -n --max-count=50")

// 출력:
// src/main/kotlin/dev/bomini/core/Agent.kt:23:suspend fun agent(
```

ripgrep의 장점:
- **속도**: 병렬 처리, SIMD 최적화로 grep보다 수십 배 빠름
- **기본 제외**: .gitignore를 자동으로 존중
- **유니코드**: UTF-8 기본 지원
- **타입 필터**: `--type kotlin`, `--type python` 등 언어별 필터

```bash
# 자주 쓰는 rg 패턴들
rg "TODO|FIXME" --type kotlin                    # 모든 TODO 찾기
rg "class.*Service" --type kotlin -l             # 파일 목록만
rg "import.*kotlinx" --type kotlin --stats       # 통계 포함
rg "fun (create|update|delete)" -P --type kotlin # Perl regex
```

---

## 4. 의미 기반 검색 (Semantic Search, 선택)

grep은 정확한 문자열/패턴 검색이다.
"사용자 인증 관련 코드"처럼 의미로 검색하려면 **임베딩(embedding) 기반 의미 검색**이 필요하다.

### 개념

```
[코드 파일들]
    ↓ 임베딩 모델로 벡터화
[코드 청크별 벡터 DB]
    ↓ 쿼리 벡터와 코사인 유사도 계산
[관련도 높은 청크 반환]
```

### 구현 아이디어 (Phase 2 이후 선택)

```kotlin
// 1. 코드베이스 인덱싱 (처음 한 번)
fun indexCodebase(dir: File): VectorIndex {
    val chunks = dir.walkTopDown()
        .filter { it.isFile && it.extension in INDEXABLE_EXTENSIONS }
        .flatMap { file ->
            splitIntoChunks(file.readText(), chunkSize = 500)
                .map { chunk -> CodeChunk(file.path, chunk) }
        }
    
    return VectorIndex(chunks.map { chunk ->
        chunk to embedText(chunk.content)  // API 호출로 임베딩
    })
}

// 2. 의미 검색 (실행 시)
fun semanticSearch(query: String, index: VectorIndex): List<CodeChunk> {
    val queryVector = embedText(query)
    return index.search(queryVector, topK = 5)
}
```

### 도구 스키마 (의미 검색)

```json
{
  "name": "search",
  "description": "Search the codebase semantically. Unlike grep which matches exact patterns, this finds conceptually related code even without exact keyword matches. Use for queries like 'user authentication logic' or 'database connection handling'.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Natural language description of what you're looking for"
      },
      "max_results": {
        "type": "integer",
        "description": "Number of results. Default 5."
      }
    },
    "required": ["query"]
  }
}
```

---

## 5. 검색 전략: grep vs 의미 검색

| 상황 | 권장 도구 |
|---|---|
| 함수명, 클래스명 알고 있을 때 | `grep` |
| 특정 문자열이 어디 있는지 | `grep` |
| TODO, FIXME 찾기 | `grep` |
| import 패턴 찾기 | `grep` |
| "인증 관련 코드가 어디 있지?" | 의미 검색 |
| "에러 처리 패턴" 찾기 | 의미 검색 |

---

## 6. 검색 결과와 context 관리

검색 결과가 많으면 context window를 낭비한다.
모델이 검색 결과를 보고 관련있는 파일만 read_file하도록 유도:

```
grep 결과 → 파일 경로 목록 → read_file(가장 관련있는 1~2개)
```

이것이 "context 효율적" 탐색 패턴이다.

---

## References

- [ripgrep Documentation](https://github.com/BurntSushi/ripgrep)
- [grep Manual](https://www.gnu.org/software/grep/manual/grep.html)
- [Java Regex (Kotlin에서 사용)](https://docs.oracle.com/javase/8/docs/api/java/util/regex/Pattern.html)
- [Text Embeddings for Semantic Search (OpenAI Blog)](https://openai.com/research/text-and-code-embeddings)
- [FAISS — Facebook AI Similarity Search (벡터 DB)](https://github.com/facebookresearch/faiss)
