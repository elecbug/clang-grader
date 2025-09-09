# C Grader

> 학생들의 C 과제를 GitHub에서 자동으로 수집하여 **컴파일 → 실행 → 채점 리포트 생성**까지 수행하는 도구

---

## 주요 기능

* **GitHub 제출 코드 자동 수집**
  * `student_map.json` 기반
  * `limit` 시한 이전 커밋까지만 인정
* **Docker 격리 환경에서 안전하게 채점**
  * GCC 컴파일 및 실행
  * 자원 제한(CPU, 메모리, 네트워크 차단 등) 가능
* **자동 채점**
  * 테스트케이스(JSON) 입력 → 기대 출력과 비교
  * 학생별 JSON 리포트 + 전체 요약 생성
* **제출현황 자동 변환**
  * 엑셀/표 형태 텍스트 → `student_map.json` 생성
  * 전각문자/한글 파일명도 자동 처리
* **유사도 검사 지원**
  * 제출 코드 간 문자열 기반 유사도 측정
  * 표절 의심 케이스 탐지 가능

---

## 실행 절차

### 0. `table.txt` 준비

- 과제란의 `엑셀 다운로드`를 통해 과제 제출 현황표를 다운로드
- 타이틀을 제외한 전체 셀을 복사하여 `./docker/data/\<HOMEWORK_NUMBER]\>table.txt`에 저장

### 1. Docker 이미지 빌드

```bash
./sh/build.sh
```

### 2. `student_map.json` 생성

```bash
./sh/setup-table.sh ./docker/data/<HOMEWORK_NUMBER> <LIMIT>
```

> - `<LIMIT>`는 과제 마감 날짜
>   - `2025-09-09T00:00:00+09:00`의 포맷을 따름

### 3. `tests.json` 준비

```json
[
  {
    "name": "add-1",
    "stdin": "1 2\n",
    "expected": "3\n"
  },
  {
    "name": "add-2",
    "stdin": "10 5\n",
    "expected": ["15\n", "15"]
  },
  {
    "name": "nonzero-exit-optional",
    "stdin": "0 0\n",
    "expected": "0\n",
    "exit_code": 0
  }
]
```

> 위와 같은 형태로 테스트케이스를 작성하여 `./docker/data/<HOMEWORK_NUMBER>/tests.json`으로 저장

### 4. 채점 실행

```bash
./sh/run.sh ./docker/data/<HOMEWORK_NUMBER>
```

```bash
GITHUB_TOKEN=ghp_xxx ./sh/run.sh ./docker/data/<HOMEWORK_NUMBER>
```

> - GitHub API rate limit 회피를 위해 토큰 사용 가능

```bash
[GITHUB_TOKEN=ghp_xxx] ./sh/nonfetch-run.sh ./docker/data/<HOMEWORK_NUMBER>
```

> - Fetch 모드를 비활성화하여 로컬에 다운로드 된 코드만으로 채점 가능

### 5. 유사도 검사(선택)

```bash
cd script
python3 similarity_report.py ../docker/data/<HOMEWORK_NUMBER> -o ./docker/data/<HOMEWORK_NUMBER>/similarity.json
```

---

## 보안/제한 설정

* 반드시 **Docker 컨테이너 내부**에서만 코드 실행
* 옵션 예시:
  * `--network=none`
  * `--cpus=1.0`
  * `--memory=256m`
  * `--timeout=2.0`
* 무한 루프/자원 과다 사용 방지

---

## 확장 아이디어

* CSV/엑셀 결과 내보내기
* 부동소수/정규식 출력 비교
* 웹 UI 대시보드 시각화
* C 언어 외 다중 언어 지원
