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

아래는 이 레포를 개발하면서 **실제로 실행한 결과**입니다.

### 커밋 메시지

```
$ git add -A
$ python main.py commit
[INFO] Git status 수집 완료: 2개 파일 변경 감지
[INFO] Git diff 수집 완료: 63줄
[SAFE] safe-mode ON (최대 10개 파일 / 200줄) | 제외 0개 파일, 초과 0개 파일 생략, 0줄 생략, 마스킹 0건
[INFO] AI API 요청 중... (model=gemini-3.5-flash, temperature=0.2, max_tokens=4096)
[INFO] 토큰 사용량: 입력 1502 / 출력 221
[INFO] AI API 호출 횟수: 1회
[DONE] 커밋 메시지 생성 완료

--- Change Summary ---
PR 초안 생성 시 커밋되지 않은 변경사항을 제외하고 경고를 출력하도록 수정했습니다. 또한, 특정 파일이 전체 줄 한도를 독점하여 다른 파일의 변경사항이 누락되는 문제를 방지하기 위해 파일별로 줄 한도를 균등하게 분배하는 로직을 도입했습니다.
----------------------------------------

--- Commit Message ---
feat: PR 생성 시 미커밋 변경 제외 및 파일별 줄 한도 분배

- main.py의 collect 함수에서 PR 대상 비교 시 커밋되지 않은 변경사항을 제외하고 경고를 표시하도록 변경
- main.py의 apply_safe_mode 함수에서 작은 파일부터 예산을 배정하여 파일 간 줄 한도를 균등하게 분배하도록 개선
- test_main.py에 큰 파일이 앞에 있어도 뒤쪽 파일이 잘리지 않고 예산이 분배되는지 검증하는 테스트 추가
----------------------------------------
※ AI 초안입니다. 내용을 검토한 뒤 적용하세요.
```

> 검토 후 적용: 버그 수정이므로 type 을 `feat` → `fix` 로 바꿔 커밋했습니다 (커밋 `a171866`). AI 초안을 그대로 쓰지 않고 사람이 확인해야 하는 이유의 실제 사례입니다.

### PR 초안

```
$ python main.py pr --base main
[INFO] 현재 브랜치: feature/commit-pr-generator (base: main)
[INFO] Git status 수집 완료: 4개 파일 변경 감지
[INFO] Git diff 수집 완료: 852줄
[SAFE] safe-mode ON (최대 10개 파일 / 200줄) | 제외 0개 파일, 초과 0개 파일 생략, 652줄 생략, 마스킹 5건 {'GOOGLE_KEY': 1, 'SECRET': 2, 'EMAIL': 1, 'PHONE': 1}
[INFO] AI API 요청 중... (model=gemini-3.5-flash, temperature=0.2, max_tokens=4096)
[INFO] 토큰 사용량: 입력 3308 / 출력 281
[INFO] AI API 호출 횟수: 1회
[DONE] PR 초안 생성 완료

--- PR Title ---
feat: safe-mode 파일별 줄 한도 분배 로직 개선 및 테스트 추가
----------------------------------------

--- PR Body ---
## Why
- 기존에는 앞 순서의 파일이 크면 전체 줄 수 한도를 모두 소모하여, 뒤쪽 파일의 변경 사항이 완전히 생략되는 문제가 있었습니다.
- 알파벳 순서 등으로 인해 중요한 핵심 파일의 변경 사항이 AI 프롬프트에서 누락되는 현상을 방지해야 합니다.

## What
- main.py: apply_safe_mode 함수 내 줄 한도 초과 처리 로직을 파일별 크기 기준 균등 분배 방식으로 변경
- test_main.py: 큰 파일이 앞에 배치되어도 뒤쪽 파일의 변경 사항이 잘리지 않고 포함되는지 검증하는 테스트 케이스 추가

## How to Test
- python test_main.py 명령어를 실행하여 추가된 줄 한도 분배 테스트를 포함한 전체 테스트가 통과하는지 확인합니다.
----------------------------------------
※ AI 초안입니다. 내용을 검토한 뒤 적용하세요.
```

### 오류 상황

```
$ python main.py commit            # 키 미설정
[ERROR] GEMINI_API_KEY 환경변수가 설정되지 않았습니다.
  예) export GEMINI_API_KEY="YOUR_KEY"   (PowerShell: $env:GEMINI_API_KEY="YOUR_KEY")

$ python main.py commit            # 잘못된 키
[ERROR] AI API 오류 HTTP 400 - 인증 실패(API Key 확인): API key not valid. Please pass a valid API key.

$ python main.py commit            # 서버 혼잡 (실제 발생)
[ERROR] AI API 오류 HTTP 503 - 서버 오류: This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.

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

#### safe-mode ON / OFF 비교 (보너스 3)

**정책 (기본값)**

| 단계 | 기준 | 설정 방법 |
|---|---|---|
| 파일 제외 | `.env`, `.env.*`, `*.pem`, `*.key`, `*secret*`, `*credential*` | `safe_mode.exclude_files` |
| 파일 수 제한 | 최대 **10개** 파일 | `--max-files`, `safe_mode.max_files` |
| 줄 수 제한 | 최대 **200줄**. 작은 파일부터 필요한 만큼 배정하고, 남은 몫은 큰 파일에 줌 | `--max-lines`, `safe_mode.max_lines` |
| 마스킹 | 기본 9개 패턴 + 사용자 정규식 | `safe_mode.mask_patterns` (`{"name", "regex"}`) |

줄 수 제한을 파일별로 나누는 이유가 있습니다. 처음에는 앞에서부터 200줄을 잘랐는데, git diff는 파일을 알파벳 순서로 나열하기 때문에 `README.md`가 한도를 다 쓰고 정작 핵심인 `main.py`는 빠졌습니다. 그 결과 AI가 기능 추가 PR을 `docs:` PR로 요약했습니다. 실제로 겪은 문제입니다.

**실험**: API Key를 하드코딩하고, 이메일·전화번호를 넣고, `.env`를 추가한 변경에 `python main.py commit`을 실행했습니다.

| | safe-mode ON (기본) | `--no-safe-mode` |
|---|---|---|
| 로그 | `제외 1개 파일, 마스킹 3건 {'GOOGLE_KEY': 1, 'EMAIL': 1, 'PHONE': 1}` | `[WARN] safe-mode OFF: diff 원문이 그대로 외부 API 로 전송됩니다.` |
| 전송된 `.env` | 전송 안 됨 | `+DB_PASSWORD=hunter2` / `+SLACK_TOKEN=xoxb-1234` |
| 전송된 `app.py` | `API_KEY = "[MASKED_GOOGLE_KEY]"`<br>`ADMIN_EMAIL = "[MASKED_EMAIL]"`<br>`(문의: [MASKED_PHONE])` | `API_KEY = "AIzaSyD-demo000…"`<br>`ADMIN_EMAIL = "admin@corp.com"`<br>`(문의: 010-1234-5678)` |
| 생성된 커밋 | `feat(app): 관리자 알림 전송 기능 추가`<br>- app.py에 웹훅을 통해 알림을 전송하는 notify 함수를 추가함<br>- app.py에 API_KEY 및 ADMIN_EMAIL 변수를 정의함<br>- 설정 관리를 위해 .env 파일을 추가함 | `feat: 관리자 알림 기능 및 환경 변수 설정 추가`<br>- app.py에 urllib.request를 사용하여 외부 웹훅으로 알림을 전송하는 notify 함수를 추가했습니다.<br>- .env 파일을 새로 생성하여 **DB_PASSWORD 및 SLACK_TOKEN 설정을 정의했습니다.** |

- OFF에서는 비밀값이 외부 API로 전송됐고, 생성된 커밋 메시지에도 비밀 **변수명**이 그대로 드러났습니다.
- ON에서는 `.env`의 파일명만 status로 전달됐기 때문에, AI가 ".env를 추가했다"는 사실만 알고 내용은 모릅니다. 요약 품질은 거의 같습니다.
- 이 실험에서 마스킹 버그도 하나 찾았습니다. 키가 35자보다 길면 마지막 글자가 새어 나갔습니다(`[MASKED_GOOGLE_KEY]0`). 정규식을 `{35,}`로 고치고 회귀 테스트를 추가했습니다.

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
