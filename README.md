# ai-gitgen

`git status` / `git diff` 결과를 AI API(Google Gemini, REST)에 보내 **커밋 메시지**와 **Pull Request 초안**을 만들어 주는 Python CLI입니다.

- Python 3.10 이상, **표준 라이브러리만 사용** (`pip install` 없음)
- API는 SDK 없이 `urllib`로 REST를 직접 호출
- `commit` / `pr` 명령마다 **AI API는 1회만 호출**
- 기본으로 **safe-mode ON**: 민감정보를 마스킹하고, 전송하는 파일·줄 수를 제한

```
git status / git diff ──▶ safe-mode(제외·제한·마스킹) ──▶ 프롬프트 + JSON 스키마
      ──▶ Gemini generateContent (1회) ──▶ JSON 응답 검증·후처리 ──▶ 터미널 출력
```

## 1. 설치

```bash
git clone https://github.com/mov-hyun/cdsy-b3-2-ai-gitgen.git
cd cdsy-b3-2-ai-gitgen
python --version   # 3.10 이상
```

다른 프로젝트에서 쓸 때는 **그 프로젝트의 루트 디렉토리**에서 `main.py` 경로를 지정해 실행합니다.

```bash
cd ~/my-project
python ~/cdsy-b3-2-ai-gitgen/main.py commit
```

## 2. 환경변수(API Key) 설정

[Google AI Studio](https://aistudio.google.com/apikey)에서 API Key를 발급받은 뒤 환경변수로 설정합니다. **키는 코드나 파일에 저장하지 않습니다.**

```bash
# macOS / Linux / Git Bash
export GEMINI_API_KEY="YOUR_KEY"
```

```powershell
# Windows PowerShell (현재 창에서만 유효)
$env:GEMINI_API_KEY="YOUR_KEY"
```

키는 URL 쿼리가 아니라 `x-goog-api-key` 헤더로 전송하므로, 프록시나 서버 로그의 URL에 남지 않습니다.

## 3. 사용법

```bash
python main.py commit              # 커밋 메시지 생성
python main.py pr                  # PR 제목/본문 생성 (작업 트리 변경 기준)
python main.py pr --base main      # main 브랜치 대비 현재 브랜치 전체 변경 기준
python main.py commit --dry-run    # API 호출 없이 전송될 프롬프트만 확인
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--model`, `-model` | `gemini-3.5-flash` | 사용할 모델 |
| `--temperature`, `-temperature` | `0.2` | 0~2. 낮을수록 같은 diff에 같은 결과 |
| `--max-tokens`, `-max-tokens` | `4096` | 최대 출력 토큰 (thinking 토큰 포함) |
| `--timeout` | `60` | API 요청 타임아웃(초) |
| `--base` | 없음 | `pr` 비교 기준 브랜치 |
| `--safe-mode` / `--no-safe-mode` | ON | 민감정보 마스킹 + 전송량 제한 |
| `--max-files` / `--max-lines` | `10` / `200` | safe-mode 전송 한도 |
| `--convention` | `.ai-gitgen.json` | 팀 컨벤션 설정 파일 (있을 때만 적용) |
| `--no-convention` | - | 컨벤션 파일 무시 |
| `--dry-run` | - | 프롬프트만 출력하고 API는 호출하지 않음 |

### 파라미터가 결과에 주는 영향

- **temperature**: 모델이 다음 토큰을 고를 때의 무작위성입니다. 커밋 메시지는 사실을 요약하는 작업이라 창의성보다 일관성이 중요해서 기본값을 `0.2`로 낮게 두었습니다. `1.0` 이상으로 올리면 표현은 다양해지지만 diff에 없는 내용이 섞일 가능성이 커집니다.
- **max_tokens**: 출력 길이의 상한입니다. 너무 작으면 JSON이 중간에 잘려(`finishReason=MAX_TOKENS`) 해석에 실패하고, 도구는 "`--max-tokens`를 늘리세요"라고 안내합니다. Gemini의 thinking 모델은 내부 추론 토큰도 이 한도에 포함되므로 넉넉하게 `4096`을 기본값으로 둡니다.
- **model**: `flash-lite` 계열은 빠르고 저렴하고, `flash` 계열은 긴 diff를 더 잘 요약합니다.

## 4. 출력 예시

### 커밋 메시지

```
$ python main.py commit
[INFO] Git status 수집 완료: 3개 파일 변경 감지
[INFO] Git diff 수집 완료: 128줄
[SAFE] safe-mode ON (최대 10개 파일 / 200줄) | 제외 0개 파일, 초과 0개 파일 생략, 0줄 생략, 마스킹 0건
[INFO] AI API 요청 중... (model=gemini-3.5-flash, temperature=0.2, max_tokens=4096)
[INFO] 토큰 사용량: 입력 2210 / 출력 180
[INFO] AI API 호출 횟수: 1회
[DONE] 커밋 메시지 생성 완료

--- Change Summary ---
git diff 를 AI 입력으로 연결해 커밋 메시지를 생성하는 CLI 를 추가했다. ...
----------------------------------------

--- Commit Message ---
feat: Git 변경 사항 기반 커밋 메시지 자동 생성 추가

- main.py: git status/diff 수집 후 Gemini API 로 전달
- 커밋 제목 72자 초과 시 단어 경계에서 자르도록 후처리
----------------------------------------
※ AI 초안입니다. 내용을 검토한 뒤 적용하세요.
```

### PR 초안

```
$ python main.py pr --base main
[INFO] 현재 브랜치: feature/commit-pr-generator (base: main)
...
[DONE] PR 초안 생성 완료

--- PR Title ---
feat: 커밋/PR 초안 자동 생성 CLI 추가
----------------------------------------

--- PR Body ---
## Why
- 커밋 메시지와 PR 설명 작성에 드는 시간을 줄이고 형식을 통일하기 위해

## What
- main.py: git status/diff 수집, Gemini REST 호출, 결과 검증·후처리
- safe-mode: .env 등 민감 파일 제외, API Key·이메일 마스킹

## How to Test
- export GEMINI_API_KEY="YOUR_KEY" 후 python main.py commit 실행
- python test_main.py 실행 시 OK 출력 확인
----------------------------------------
```

### 오류 상황

```
$ python main.py commit            # 키 미설정
[ERROR] GEMINI_API_KEY 환경변수가 설정되지 않았습니다.
  예) export GEMINI_API_KEY="YOUR_KEY"   (PowerShell: $env:GEMINI_API_KEY="YOUR_KEY")

$ python main.py commit            # 잘못된 키
[ERROR] AI API 오류 HTTP 400 - 인증 실패(API Key 확인): API key not valid. Please pass a valid API key.

$ python main.py commit            # 변경 없음
[INFO] 변경 사항이 없습니다. 커밋 메시지를 생성하지 않고 종료합니다.
```

| 상황 | 메시지 |
|---|---|
| 키 없음 | 환경변수 설정 방법 안내 (Git 작업 전에 먼저 검사) |
| 400 / 401 / 403 | 인증 실패 또는 잘못된 요청 + 서버가 준 원인 메시지 |
| 404 | 모델명 확인 (`--model`) |
| 429 | 요청 한도 초과, 잠시 후 재시도 |
| 5xx | 서버 오류 |
| 네트워크 끊김 / 타임아웃 | 연결 불가 사유 / 타임아웃 초 |
| 응답이 잘림 | `--max-tokens` 증가 안내 |

## 5. 결과 품질을 제어하는 방법

1. **구조화 출력**: 모델에게 완성된 텍스트를 받지 않고, `responseSchema`로 `{type, scope, subject, bullets}`나 `{title, why, what, how_to_test}` 형태의 JSON을 받습니다. 헤더와 형식은 코드가 직접 조립하므로 "Why 섹션이 빠진" 결과가 나올 수 없습니다.
2. **프롬프트 구성**: 시스템 프롬프트에는 역할과 금지사항(diff에 없는 내용 지어내지 않기, `[MASKED_*]` 복원하지 않기)을 넣고, 사용자 프롬프트에는 작업 → 규칙(컨벤션) → `git status` → `git diff` 순서로 넣습니다.
3. **검증·후처리**: 재생성 대신 후처리를 택했습니다. API를 한 번 더 부르면 비용과 시간이 두 배가 되기 때문입니다.

| 규칙 | 처리 |
|---|---|
| 커밋 제목 50자 권장 | 초과 시 `[WARN]` 표시 |
| 커밋 제목 최대 72자 | 단어 경계에서 잘라내고 `…` 추가 |
| 허용되지 않은 type (`Feature` 등) | 컨벤션의 첫 type으로 교체 |
| 커밋 본문 | 파일/모듈 언급 + 불릿 1~3개 |
| PR 제목 최대 80자 | 잘라내기 |
| PR Why/What/How to Test | 헤더 필수. 불릿이 비면 `- (작성 필요)`를 넣고 경고 |

## 6. 주의사항 / 운영 관점

### 민감정보 (safe-mode)

`git diff`에는 실수로 넣은 API Key나 개인정보가 들어 있을 수 있고, 이 도구는 diff를 **외부 서버로 전송**합니다. 그래서 safe-mode는 기본으로 켜져 있고, 다음 순서로 동작합니다.

1. **파일 제외**: `.env`, `.env.*`, `*.pem`, `*.key`, `*secret*`, `*credential*`에 해당하는 파일은 diff 전체를 보내지 않습니다.
2. **파일 수 제한**: 최대 10개 파일까지만 보내고, 나머지는 생략합니다.
3. **줄 수 제한**: 최대 200줄까지만 보내고, `... (N줄 생략됨)`을 붙입니다.
4. **정규식 마스킹**:

| 이름 | 대상 |
|---|---|
| `PRIVATE_KEY` | `-----BEGIN ... PRIVATE KEY-----` 블록 |
| `GOOGLE_KEY` / `OPENAI_KEY` / `GITHUB_TOKEN` / `AWS_KEY` | `AIza…`, `sk-…`, `ghp_…`, `AKIA…` |
| `JWT` | `eyJ….….…` |
| `SECRET` | `password` / `secret` / `token` / `api_key`가 들어간 이름에 대입된 문자열 값 (함수 호출은 제외) |
| `EMAIL` | 이메일 주소 |
| `PHONE` | 한국 휴대폰 번호 |

실행할 때마다 `[SAFE]` 로그에 몇 건을 제외·생략·마스킹했는지 표시합니다. 실제로 무엇이 전송되는지는 `--dry-run`으로 미리 확인할 수 있습니다. 한도는 `--max-files` / `--max-lines` 옵션이나 설정 파일로 바꿀 수 있습니다.

### 비용 / 요청 횟수

- 1회 실행에 API 호출은 정확히 1회이며, 로그에 `AI API 호출 횟수`와 토큰 사용량을 출력합니다.
- 형식 오류를 재요청으로 고치지 않고 후처리하므로 호출 횟수가 늘지 않습니다.
- safe-mode의 200줄 제한은 입력 토큰(비용)의 상한 역할도 합니다. 큰 변경은 커밋을 나누는 편이 결과도 더 좋습니다.
- 무료 티어에는 분당 요청 수 제한이 있습니다. `429`가 나오면 잠시 뒤 다시 실행하세요.

### 결과 사용

생성된 텍스트는 **초안**입니다. diff만 보고 "왜"를 추론하므로 실제 의도와 다를 수 있습니다. 반드시 검토하고 고친 뒤 `git commit`이나 PR 작성에 사용하세요. 이 도구는 `git commit`, `git push`, PR 생성을 **직접 하지 않습니다**.

## 7. 팀 컨벤션 커스터마이징 (보너스 2)

프로젝트 루트에 `.ai-gitgen.json`이 있으면 자동으로 적용합니다. 다른 경로의 파일은 `--convention path`로 지정합니다. 예시는 [.ai-gitgen.example.json](.ai-gitgen.example.json)에 있습니다.

| 키 | 설명 |
|---|---|
| `language` | 결과 언어 (`ko`, `en` ...) |
| `commit_types` | 허용할 커밋 prefix. 벗어나면 첫 번째 값으로 교정 |
| `require_scope` | `true`이면 `type(scope): subject` 형식 강제 |
| `subject_max` | 권장 제목 길이 |
| `extra_rules` | 프롬프트에 추가할 팀 규칙(문장) |
| `pr_checklist` | PR 본문 끝에 붙일 `## Checklist` 항목 |
| `safe_mode` | `max_files`, `max_lines`, `exclude_files`, `mask_patterns` |

<!-- TODO: 대상 레포 컨벤션 분석 결과 + 적용 전/후 비교 -->

## 8. 테스트

```bash
python test_main.py   # API 호출 없이 마스킹·전송 제한·후처리·검증 로직 확인
```

## 파일 구조

```
main.py                  # CLI 전체 (git 수집 / safe-mode / 프롬프트 / API / 후처리)
test_main.py             # assert 기반 셀프 체크
.ai-gitgen.example.json  # 팀 컨벤션 설정 예시
```
