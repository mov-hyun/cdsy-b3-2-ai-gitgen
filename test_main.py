"""API 호출 없이 검증 가능한 로직(마스킹·전송 제한·후처리·검증) 셀프 체크. 실행: python test_main.py"""
import main

conv = main.load_convention(None)[0]

# 마스킹: 키 이름은 남기고 값만 가린다, 함수 호출 값은 건드리지 않는다
text, counts = main.mask(
    'GEMINI_API_KEY="AIzaSyA1234567890abcdefghijklmnopqrstuv"\n'
    "password = 'hunter2!!'\n"
    "token = get_token()\n"
    "contact: dev@example.com, 010-1234-5678\n"
)
assert "AIzaSy" not in text and "hunter2" not in text, text
assert "password = [MASKED_SECRET]" in text, text
assert "token = get_token()" in text, text
assert "[MASKED_EMAIL]" in text and "[MASKED_PHONE]" in text, text
assert counts["EMAIL"] == 1 and counts["PHONE"] == 1, counts

# 사용자 정의 패턴
text, counts = main.mask("user_id: KR-998877", [("USER_ID", r"KR-\d{6}")])
assert text == "user_id: [MASKED_USER_ID]" and counts == {"USER_ID": 1}

# 전송 제한: .env 제외, 파일 수·줄 수 제한
diff = "".join(f"diff --git a/f{i}.py b/f{i}.py\n+line\n+line\n" for i in range(5))
diff += "diff --git a/.env b/.env\n+SECRET=abc\n"
policy = dict(conv["safe_mode"], max_files=3, max_lines=7)
out, rep = main.apply_safe_mode(diff, policy)
assert rep["excluded"] == [".env"], rep
assert rep["dropped_files"] == ["f3.py", "f4.py"], rep
assert rep["truncated_lines"] == 2 and "f2.py" in out and "SECRET" not in out, (rep, out)

# 커밋 후처리: 잘못된 type 교정, 72자 초과 제목 절단, 불릿 정리
msg, warns = main.finalize_commit(
    {"type": "Feature", "scope": "", "subject": "아주 " * 40, "bullets": ["- main.py 수정", "", "•  README 갱신"]}, conv)
subject, body = msg.split("\n\n")
assert subject.startswith("feat: ") and len(subject) <= main.COMMIT_SUBJECT_MAX, subject
assert body == "- main.py 수정\n- README 갱신", body
assert len(warns) == 3, warns

# PR 후처리: 빈 섹션이 와도 Why/What/How to Test + 불릿 보장, 제목 80자
title, body, warns = main.finalize_pr({"title": "feat: " + "x" * 100, "why": [], "what": ["A"], "how_to_test": ["run"]}, conv)
assert len(title) <= main.PR_TITLE_MAX, title
assert main.validate_pr_body(body) == [], body
assert "## Why\n- (작성 필요)" in body and len(warns) == 2, (body, warns)
assert main.validate_pr_body("## Why\n- a\n\n## What\n\n## How to Test\n- b") == ["What"]

# 컨벤션: scope 필수 + 체크리스트
c = dict(conv, require_scope=True, pr_checklist=["테스트 통과"])
msg, _ = main.finalize_commit({"type": "fix", "scope": "", "subject": "버그 수정", "bullets": []}, c)
assert msg == "fix(core): 버그 수정", msg
assert main.finalize_pr({"title": "t", "why": ["a"], "what": ["b"], "how_to_test": ["c"]}, c)[1].endswith("- [ ] 테스트 통과")

print("OK: all checks passed")
