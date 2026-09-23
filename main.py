"""ai-gitgen: git status/diff 를 AI API(Gemini REST)에 넘겨 커밋 메시지·PR 초안을 생성하는 CLI.

사용법: python main.py commit | pr [--model ...] [--temperature ...] [--max-tokens ...]
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
API_KEY_ENV = "GEMINI_API_KEY"
DEFAULT_MODEL = "gemini-3.5-flash"
CONFIG_FILE = ".ai-gitgen.json"

COMMIT_SUBJECT_MAX = 72  # 50자 권장, 72자 초과 시 잘라냄
PR_TITLE_MAX = 80
SEP = "-" * 40

# 기본 컨벤션. .ai-gitgen.json 이 있으면 같은 키를 덮어쓴다.
DEFAULT_CONVENTION = {
    "language": "ko",
    "commit_types": ["feat", "fix", "docs", "refactor", "test", "chore"],
    "require_scope": False,
    "subject_max": 50,
    "pr_checklist": [],
    "extra_rules": [],
    "safe_mode": {
        "max_files": 10,
        "max_lines": 200,
        "exclude_files": [".env", ".env.*", "*.pem", "*.key", "*secret*", "*credential*"],
        "mask_patterns": [],
    },
}

# (이름, 정규식) — 매칭 부분을 [MASKED_이름] 으로 바꾼다.
BASE_MASK_PATTERNS = [
    ("PRIVATE_KEY", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ("GOOGLE_KEY", r"AIza[0-9A-Za-z_\-]{35}"),
    ("OPENAI_KEY", r"sk-[A-Za-z0-9_\-]{20,}"),
    ("GITHUB_TOKEN", r"gh[pousr]_[A-Za-z0-9]{36,}"),
    ("AWS_KEY", r"AKIA[0-9A-Z]{16}"),
    ("JWT", r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    # 키 이름(api_key= 등)은 캡처 그룹으로 남기고 값만 가린다. 함수 호출처럼 괄호가 있는 값은 제외.
    ("SECRET", r"""(?im)(\b\w*(?:password|passwd|secret|token|api_?key)\w*\b)(\s*[:=]\s*)(?!["']?\[MASKED_)(?:"[^"\n]{4,}"|'[^'\n]{4,}'|[\w\-+/=.]{8,}$)"""),
    ("EMAIL", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    ("PHONE", r"\b01[016789]-?\d{3,4}-?\d{4}\b"),
]


class GenError(Exception):
    """사용자에게 그대로 보여줄 오류."""


def log(level, msg):
    print(f"[{level}] {msg}", file=sys.stderr if level == "ERROR" else sys.stdout)


# ---------------------------------------------------------------- git

def git(*args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise GenError("git 명령을 찾을 수 없습니다. Git 설치 여부를 확인하세요.")
    if r.returncode != 0:
        raise GenError(f"git {' '.join(args)} 실패: {r.stderr.strip()}")
    return r.stdout


def collect(base=None):
    """git status / git diff 를 수집한다. base 가 있으면 base 대비 전체 변경(PR 용)."""
    if not os.path.isdir(".git"):
        raise GenError("Git 프로젝트 루트 디렉토리에서 실행하세요. (.git 폴더가 없습니다)")
    status = git("status", "--porcelain=v1", "-b")
    lines = status.splitlines()
    branch = lines[0][3:].split("...")[0] if lines and lines[0].startswith("## ") else "?"
    files = [l[3:] for l in lines[1:] if l.strip()]

    has_head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0
    if base:
        git("rev-parse", "--verify", "-q", base)  # 없는 브랜치면 GenError
        # PR 에 올라가는 건 커밋뿐이므로 커밋되지 않은 변경은 제외한다
        diff = git("diff", f"{base}...HEAD")
        if files:
            log("WARN", f"커밋되지 않은 변경 {len(files)}개는 PR 초안에 포함되지 않습니다.")
        files = git("diff", "--name-only", f"{base}...HEAD").split()
    else:
        # 스테이징 여부와 무관하게 마지막 커밋 대비 전체 변경. 첫 커밋 전이면 staged 만.
        diff = git("diff", "HEAD") if has_head else git("diff", "--cached")
    return {"branch": branch, "status": status, "files": files, "diff": diff}


# ---------------------------------------------------------------- safe mode

def split_diff(diff):
    """diff 텍스트를 [(파일경로, 블록텍스트)] 로 나눈다."""
    blocks = re.split(r"(?m)^(?=diff --git )", diff)
    out = []
    for b in blocks:
        if not b.strip():
            continue
        m = re.match(r"diff --git a/(\S+) b/(\S+)", b)
        out.append((m.group(2) if m else "?", b))
    return out


def mask(text, extra_patterns=()):
    """민감정보 패턴을 마스킹하고 (결과, {패턴이름: 개수}) 를 반환. 정규식의 캡처 그룹은 남긴다."""
    counts = {}
    for name, pattern in [*BASE_MASK_PATTERNS, *extra_patterns]:
        def repl(m, name=name):
            counts[name] = counts.get(name, 0) + 1
            return "".join(g or "" for g in m.groups()) + f"[MASKED_{name}]"  # 캡처 그룹은 보존
        text = re.sub(pattern, repl, text)
    return text, counts


def apply_safe_mode(diff, policy):
    """파일 제외 → 파일 수 제한 → 줄 수 제한 → 마스킹. (diff, 리포트) 반환."""
    report = {"excluded": [], "dropped_files": [], "truncated_lines": 0, "masked": {}}
    kept = []
    for path, block in split_diff(diff):
        name = path.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in policy["exclude_files"]):
            report["excluded"].append(path)
        elif len(kept) >= policy["max_files"]:
            report["dropped_files"].append(path)
        else:
            kept.append(block)

    # 줄 한도를 파일별로 나눠 준다: 작은 파일부터 필요한 만큼 가져가고 남는 몫은 큰 파일에게.
    # (앞에서부터 자르면 알파벳 순서상 앞 파일이 한도를 다 써서 핵심 파일이 빠진다)
    blocks = [b.splitlines() for b in kept]
    budget, left = {}, policy["max_lines"]
    for n, i in enumerate(sorted(range(len(blocks)), key=lambda i: len(blocks[i]))):
        budget[i] = min(len(blocks[i]), left // (len(blocks) - n))
        left -= budget[i]
    out = []
    for i, b in enumerate(blocks):
        out += b[: budget[i]]
        if len(b) > budget[i]:
            report["truncated_lines"] += len(b) - budget[i]
            out.append(f"... ({len(b) - budget[i]}줄 생략됨)")

    extra = [(p.get("name", "CUSTOM"), p["regex"]) for p in policy["mask_patterns"]]
    text, report["masked"] = mask("\n".join(out), extra)
    return text, report


# ---------------------------------------------------------------- convention

def load_convention(path):
    conv = json.loads(json.dumps(DEFAULT_CONVENTION))  # deep copy
    if not path:
        return conv, None
    if not os.path.exists(path):
        if path == CONFIG_FILE:
            return conv, None
        raise GenError(f"컨벤션 파일을 찾을 수 없습니다: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
    except json.JSONDecodeError as e:
        raise GenError(f"컨벤션 파일 JSON 형식 오류 ({path}): {e}")
    conv["safe_mode"].update(user.pop("safe_mode", {}))
    conv.update(user)
    return conv, path


# ---------------------------------------------------------------- prompt

COMMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "변경 사항 전체를 2~3문장으로 요약"},
        "type": {"type": "string"},
        "scope": {"type": "string", "description": "변경된 주요 모듈/디렉토리. 없으면 빈 문자열"},
        "subject": {"type": "string", "description": "type/scope 를 제외한 커밋 제목 본문"},
        "bullets": {"type": "array", "items": {"type": "string"}, "description": "핵심 변경 1~3개"},
    },
    "required": ["summary", "type", "scope", "subject", "bullets"],
}

PR_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "변경 사항 전체를 2~3문장으로 요약"},
        "title": {"type": "string"},
        "why": {"type": "array", "items": {"type": "string"}},
        "what": {"type": "array", "items": {"type": "string"}},
        "how_to_test": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "title", "why", "what", "how_to_test"],
}

SYSTEM_PROMPT = """너는 시니어 개발자이자 코드 리뷰어다. 주어진 git status 와 git diff 만 근거로
커밋 메시지나 Pull Request 초안을 작성한다.
- diff 에 없는 내용(추측한 동기, 존재하지 않는 테스트)을 지어내지 않는다.
- '무엇을 바꿨는지'보다 '왜/무엇이 달라지는지'를 중심으로 쓴다.
- 파일명·함수명은 백틱 없이 그대로 쓴다.
- [MASKED_*] 로 가려진 값은 민감정보이므로 추측하거나 복원하지 않는다.
- 반드시 지정된 JSON 스키마로만 응답한다."""


def lang_rule(conv):
    return "모든 문장은 한국어로 작성한다." if conv["language"] == "ko" else f"Write everything in {conv['language']}."


def build_prompt(kind, data, diff, conv):
    rules = [lang_rule(conv)]
    if kind == "commit":
        rules += [
            f"type 은 다음 중 하나: {', '.join(conv['commit_types'])}",
            "scope 는 반드시 채운다 (변경된 주요 모듈명, 소문자)." if conv["require_scope"]
            else "scope 는 한 모듈에 집중된 변경일 때만 채우고, 아니면 빈 문자열.",
            f"subject 는 '{{type}}(scope): ' 를 붙였을 때 {conv['subject_max']}자 이내. 명령형·현재형, 마침표 없음.",
            "bullets 는 1~3개. 변경된 파일(모듈)명을 1개 이상 언급하고, 각 불릿은 한 줄.",
        ]
    else:
        rules += [
            f"title 은 Conventional Commit 형식({'/'.join(conv['commit_types'])}: ...)으로 {PR_TITLE_MAX}자 이내 한 줄.",
            "why: 변경 배경/문제 1~3개. diff 에서 읽히는 근거만.",
            "what: 핵심 변경 사항 2~5개. 파일/모듈명 포함.",
            "how_to_test: 리뷰어가 따라 할 수 있는 구체적 명령·확인 절차 1~4개.",
        ]
    rules += conv["extra_rules"]
    rule_text = "\n".join(f"- {r}" for r in rules)
    head = f"현재 브랜치: {data['branch']}\n" if kind == "pr" else ""
    return (
        f"## 작업\n{'커밋 메시지' if kind == 'commit' else 'Pull Request 제목과 본문'}을 작성하라.\n\n"
        f"## 규칙\n{rule_text}\n\n"
        f"## git status\n{head}```\n{data['status']}```\n\n"
        f"## git diff\n```diff\n{diff}\n```"
    )


# ---------------------------------------------------------------- AI API

def get_api_key():
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise GenError(f'{API_KEY_ENV} 환경변수가 설정되지 않았습니다.\n'
                       f'  예) export {API_KEY_ENV}="YOUR_KEY"   (PowerShell: $env:{API_KEY_ENV}="YOUR_KEY")')
    return key


def call_ai(prompt, schema, args, key):
    """Gemini generateContent REST 호출 → 파싱된 JSON dict 반환."""
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": args.temperature,
            "maxOutputTokens": args.max_tokens,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    req = urllib.request.Request(
        API_URL.format(model=args.model),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},  # 키는 URL 이 아닌 헤더로
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            res = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        reason = {400: "잘못된 요청(모델명/파라미터 확인)", 401: "인증 실패(API Key 확인)",
                  403: "권한 없음(API Key 권한/유효성 확인)", 404: "모델을 찾을 수 없음(--model 확인)",
                  429: "요청 한도 초과(잠시 후 재시도)"}.get(e.code, "서버 오류" if e.code >= 500 else "요청 실패")
        if "API key" in str(detail):  # Gemini 는 잘못된 키에 400 을 준다
            reason = "인증 실패(API Key 확인)"
        raise GenError(f"AI API 오류 HTTP {e.code} - {reason}: {detail}")
    except urllib.error.URLError as e:
        raise GenError(f"네트워크 오류로 AI API 에 연결할 수 없습니다: {e.reason}")
    except TimeoutError:
        raise GenError(f"AI API 응답 시간 초과 ({args.timeout}초)")

    cand = (res.get("candidates") or [{}])[0]
    finish = cand.get("finishReason")
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    if not text:
        block = res.get("promptFeedback", {}).get("blockReason")
        raise GenError(f"AI 응답이 비어 있습니다 (finishReason={finish}, blockReason={block}). "
                       "--max-tokens 를 늘려 보세요.")
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        hint = " 출력이 잘렸습니다. --max-tokens 를 늘리세요." if finish == "MAX_TOKENS" else ""
        raise GenError(f"AI 응답을 JSON 으로 해석할 수 없습니다.{hint}")
    usage = res.get("usageMetadata", {})
    log("INFO", f"토큰 사용량: 입력 {usage.get('promptTokenCount', '?')} / 출력 {usage.get('candidatesTokenCount', '?')}")
    return out


# ---------------------------------------------------------------- 검증·후처리

def clip(text, limit):
    """한 줄로 만들고 limit 자를 넘으면 단어 경계에서 자른다."""
    text = " ".join(str(text).split()).rstrip(".")
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"


def clean_bullets(items):
    items = [" ".join(str(i).split()).lstrip("-*• ").strip() for i in items or []]
    return [i for i in items if i]


def finalize_commit(r, conv):
    """AI 결과를 검증·후처리해 (메시지, 경고목록) 반환."""
    warnings = []
    ctype = str(r.get("type", "")).strip().lower()
    if ctype not in conv["commit_types"]:
        warnings.append(f"허용되지 않은 type '{ctype}' → '{conv['commit_types'][0]}' 로 대체")
        ctype = conv["commit_types"][0]
    scope = str(r.get("scope", "")).strip().lower()
    if conv["require_scope"] and not scope:
        warnings.append("scope 필수 규칙인데 비어 있음 → 'core' 로 대체")
        scope = "core"
    prefix = f"{ctype}({scope}): " if scope else f"{ctype}: "
    subject = prefix + str(r.get("subject", "")).strip()
    if len(subject) > conv["subject_max"]:
        warnings.append(f"커밋 제목 {len(subject)}자 > 권장 {conv['subject_max']}자")
    if len(subject) > COMMIT_SUBJECT_MAX:
        warnings.append(f"커밋 제목을 최대 {COMMIT_SUBJECT_MAX}자로 잘라냄")
    subject = clip(subject, COMMIT_SUBJECT_MAX)
    body = "\n".join(f"- {b}" for b in clean_bullets(r.get("bullets"))[:3])
    return subject + ("\n\n" + body if body else ""), warnings


def finalize_pr(r, conv):
    warnings = []
    title = clip(r.get("title", ""), PR_TITLE_MAX)
    if len(" ".join(str(r.get("title", "")).split())) > PR_TITLE_MAX:
        warnings.append(f"PR 제목을 최대 {PR_TITLE_MAX}자로 잘라냄")
    sections = []
    for header, key in (("Why", "why"), ("What", "what"), ("How to Test", "how_to_test")):
        items = clean_bullets(r.get(key))
        if not items:
            warnings.append(f"'{header}' 섹션 불릿 없음 → 작성 필요 표시 추가")
            items = ["(작성 필요)"]
        sections.append(f"## {header}\n" + "\n".join(f"- {i}" for i in items))
    if conv["pr_checklist"]:
        sections.append("## Checklist\n" + "\n".join(f"- [ ] {c}" for c in conv["pr_checklist"]))
    return title, "\n\n".join(sections), warnings


def validate_pr_body(body):
    """PR 본문이 Why/What/How to Test 헤더 + 각 1개 이상 불릿을 갖는지 검사. 누락 목록 반환."""
    missing = []
    for header in ("Why", "What", "How to Test"):
        m = re.search(rf"(?m)^## {re.escape(header)}\n((?:- .+\n?)+)", body)
        if not m:
            missing.append(header)
    return missing


# ---------------------------------------------------------------- CLI

def section(title, text):
    print(f"\n--- {title} ---\n{text}\n{SEP}")


def run(args):
    key = None if args.dry_run else get_api_key()  # git 작업 전에 먼저 확인
    conv, conv_path = load_convention(None if args.no_convention else args.convention)
    if conv_path:
        log("INFO", f"컨벤션 적용: {conv_path}")
    if args.max_files is not None:
        conv["safe_mode"]["max_files"] = args.max_files
    if args.max_lines is not None:
        conv["safe_mode"]["max_lines"] = args.max_lines

    data = collect(args.base if args.command == "pr" else None)
    if not data["files"] and not data["diff"].strip():
        log("INFO", "변경 사항이 없습니다. " +
            ("커밋 메시지를" if args.command == "commit" else "PR 초안을") + " 생성하지 않고 종료합니다.")
        return 0
    if args.command == "pr":
        log("INFO", f"현재 브랜치: {data['branch']}" + (f" (base: {args.base})" if args.base else ""))
    log("INFO", f"Git status 수집 완료: {len(data['files'])}개 파일 변경 감지")
    log("INFO", f"Git diff 수집 완료: {len(data['diff'].splitlines())}줄")
    if not data["diff"].strip():
        log("WARN", "diff 가 비어 있습니다 (새 파일만 있다면 git add 후 다시 실행하세요). 파일 목록만 전달합니다.")

    diff = data["diff"]
    if args.safe_mode:
        diff, rep = apply_safe_mode(diff, conv["safe_mode"])
        p = conv["safe_mode"]
        log("SAFE", f"safe-mode ON (최대 {p['max_files']}개 파일 / {p['max_lines']}줄)"
            f" | 제외 {len(rep['excluded'])}개 파일, 초과 {len(rep['dropped_files'])}개 파일 생략,"
            f" {rep['truncated_lines']}줄 생략, 마스킹 {sum(rep['masked'].values())}건 {rep['masked'] or ''}")
        if rep["excluded"]:
            log("SAFE", f"전송 제외 파일: {', '.join(rep['excluded'])}")
    else:
        log("WARN", "safe-mode OFF: diff 원문이 그대로 외부 API 로 전송됩니다.")

    prompt = build_prompt(args.command, data, diff, conv)
    if args.dry_run:
        section("Prompt (dry-run, API 미호출)", prompt)
        log("INFO", "AI API 호출 횟수: 0회")
        return 0

    log("INFO", f"AI API 요청 중... (model={args.model}, temperature={args.temperature}, max_tokens={args.max_tokens})")
    result = call_ai(prompt, COMMIT_SCHEMA if args.command == "commit" else PR_SCHEMA, args, key)
    log("INFO", "AI API 호출 횟수: 1회")

    if args.command == "commit":
        message, warnings = finalize_commit(result, conv)
        log("DONE", "커밋 메시지 생성 완료")
        section("Change Summary", str(result.get("summary", "")).strip())
        section("Commit Message", message)
    else:
        title, body, warnings = finalize_pr(result, conv)
        missing = validate_pr_body(body)
        if missing:  # finalize_pr 가 보장하므로 여기 오면 버그
            raise GenError(f"PR 본문 형식 검증 실패: {missing}")
        log("DONE", "PR 초안 생성 완료")
        section("Change Summary", str(result.get("summary", "")).strip())
        section("PR Title", title)
        section("PR Body", body)
    for w in warnings:
        log("WARN", f"후처리: {w}")
    print("※ AI 초안입니다. 내용을 검토한 뒤 적용하세요.")
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="main.py", description="git diff 기반 AI 커밋 메시지 / PR 초안 생성기")
    p.add_argument("command", choices=["commit", "pr"], help="commit: 커밋 메시지 / pr: PR 제목·본문")
    p.add_argument("--model", "-model", default=DEFAULT_MODEL, help=f"AI 모델 (기본 {DEFAULT_MODEL})")
    p.add_argument("--temperature", "-temperature", type=float, default=0.2,
                   help="0~2, 낮을수록 일관된 결과 (기본 0.2)")
    p.add_argument("--max-tokens", "-max-tokens", type=int, default=4096,
                   help="최대 출력 토큰 (기본 4096, thinking 토큰 포함)")
    p.add_argument("--timeout", type=int, default=60, help="API 요청 타임아웃 초 (기본 60)")
    p.add_argument("--base", default=None, help="pr: 비교 기준 브랜치 (예: main). 생략 시 작업 트리 변경만")
    p.add_argument("--safe-mode", "-safe-mode", action=argparse.BooleanOptionalAction, default=True,
                   help="민감정보 마스킹 + 전송량 제한 (기본 ON, 끄려면 --no-safe-mode)")
    p.add_argument("--max-files", type=int, help="safe-mode 전송 최대 파일 수 (기본 10)")
    p.add_argument("--max-lines", type=int, help="safe-mode 전송 최대 diff 줄 수 (기본 200)")
    p.add_argument("--convention", default=CONFIG_FILE, help=f"컨벤션 설정 파일 (기본 {CONFIG_FILE})")
    p.add_argument("--no-convention", action="store_true", help="컨벤션 파일 무시하고 기본 규칙 사용")
    p.add_argument("--dry-run", action="store_true", help="API 호출 없이 전송될 프롬프트만 출력")
    args = p.parse_args(argv)
    if not 0 <= args.temperature <= 2:
        p.error("--temperature 는 0~2 사이여야 합니다.")
    if args.max_tokens <= 0:
        p.error("--max-tokens 는 양수여야 합니다.")
    return args


def main(argv=None):
    for s in (sys.stdout, sys.stderr):  # Windows 콘솔 한글 깨짐 방지
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    try:
        return run(parse_args(argv))
    except GenError as e:
        log("ERROR", str(e))
        return 1
    except re.error as e:
        log("ERROR", f"mask_patterns 정규식 오류: {e}")
        return 1
    except KeyboardInterrupt:
        log("ERROR", "사용자에 의해 중단되었습니다.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
