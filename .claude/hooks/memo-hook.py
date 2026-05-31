#!/usr/bin/env python3
"""
Stop hook: 마지막 Q&A를 분석해서 학습 메모를 docs/memo에 자동 저장.
claude -p 서브프로세스가 교육 여부 판단 + 문서 작성을 담당한다.
"""
import json
import sys
import os
import subprocess

RECURSION_GUARD = "MEMO_HOOK_RUNNING"


def extract_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def main():
    # 재귀 방지: 이 훅이 트리거한 claude -p 가 다시 훅을 부르지 않도록
    if os.environ.get(RECURSION_GUARD):
        return

    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    transcript = data.get("transcript", [])

    # 마지막 assistant 응답 위치 탐색
    last_asst_idx = next(
        (i for i in range(len(transcript) - 1, -1, -1)
         if transcript[i].get("role") == "assistant"),
        None,
    )
    if last_asst_idx is None:
        return

    # 그 직전 user 메시지 탐색
    last_user_idx = next(
        (i for i in range(last_asst_idx - 1, -1, -1)
         if transcript[i].get("role") == "user"),
        None,
    )
    if last_user_idx is None:
        return

    user_msg = extract_text(transcript[last_user_idx]).strip()
    asst_msg = extract_text(transcript[last_asst_idx]).strip()

    if not user_msg or not asst_msg:
        return

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    env = os.environ.copy()
    env[RECURSION_GUARD] = "1"

    subprocess.run(
        ["claude", "-p", f"/memo-writer Q: {user_msg}\n\nA: {asst_msg}",
         "--allowedTools", "Read,Write,Edit,LS"],
        cwd=project_dir,
        env=env,
        capture_output=True,
        timeout=60,
    )


if __name__ == "__main__":
    main()
