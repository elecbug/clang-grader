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

## 디렉터리 구조 예시

```
.
├── README.md
├── LICENSE
├── docs
│   └── rule.md
├── sh
│   ├── build.sh
│   ├── pre-run.sh
│   ├── nonfetch-run.sh
│   └── run.sh
├── docker
│   ├── dockerfile
│   ├── fetch_and_stage.py
│   └── run_tests.py
└── script
    ├── make_student_map.py
    └── similarity_report.py
```

---

## 주요 구성 요소

### 1. dockerfile

* 기반: Debian slim
* 포함: `gcc`, `make`, `libc-dev`, `python3`
* 엔트리포인트: `python3 run_tests.py`
* 목적: 학생 코드 실행을 **격리/안전**하게 수행

### 2. build.sh

```bash
#!/usr/bin/env bash
docker build -t c-stdin-tester docker
```

* 채점용 Docker 이미지 빌드

### 3. run\_tests.py

* 단일 학생 소스 코드 채점
* 기능:

  1. GCC로 컴파일
  2. 테스트케이스(stdin 입력 제공) 실행
  3. 출력 비교
  4. JSON 리포트 작성
* 옵션:

  * `--src-dir`: 소스 폴더
  * `--tests`: 테스트 JSON
  * `--report`: 결과 저장 경로
  * `--summarize-dir`: 여러 리포트 요약

### 4. run.sh

* 전체 채점 파이프라인 자동화

1. `fetch_and_stage.py` 실행 → GitHub에서 소스코드 수집
2. Docker 실행 → 학생별 채점
3. 결과를 `reports/<suite>/`에 저장
4. 요약 테이블 출력

### 5. fetch\_and\_stage.py

* GitHub에서 학생 제출 코드를 다운로드
* 특징:

  * blob/raw URL 처리
  * 한글/특수문자 파일명 안전 처리
  * `limit` 이전 마지막 커밋만 수집
  * 대표 파일(`main.c`가 아닐 수도 있음)도 반드시 보존
  * `.c`, `.h` 파일 전체 수집
* 실행 예:

```bash
python3 fetch_and_stage.py \
  --map data/hw-test/student_map.json \
  --suite hw-test \
  --data-root data \
  --rename-to main.c \
  --respect-limit
```

### 6. make\_student\_map.py

* 제출현황 표(엑셀 → 텍스트)에서 student\_map.json 생성
* 자동으로 ID와 GitHub URL 추출
* 실행 예:

```bash
python3 make_student_map.py table.txt \
  --limit 2025-09-09T00:00:00Z \
  --only-submitted \
  --pretty \
  -o data/hw-test/student_map.json
```

### 7. similarity\_report.py

* 폴더 내 모든 학생 코드 비교
* 학생별 "가장 유사한 다른 코드"와 유사도 점수 산출
* 실행 예:

```bash
python3 similarity_report.py data/hw-test -o reports/hw-test/sim.json
```

---

## student\_map.json 예시

```json
{
  "limit": "2025-09-09T00:00:00Z",
  "students": [
    {
      "id": "5880642",
      "url": "https://github.com/stu1/Project1/blob/master/Project1/ex01.c"
    },
    {
      "id": "5880397",
      "url": "https://github.com/stu2/DataStructure/blob/master/0904/0904.c"
    }
  ]
}
```

---

## 실행 절차

### 1. Docker 이미지 빌드

```bash
./sh/build.sh
```

### 2. student\_map.json 생성

```bash
./sh/pre-run.sh docker/data/hw-test/ 2025-09-09T00:00:00+09:00
```

### 3. 채점 실행

```bash
./sh/run.sh docker/data/hw-test
```

GitHub API rate limit 회피를 위해 토큰 사용 가능:

```bash
GITHUB_TOKEN=ghp_xxx ./sh/run.sh docker/data/hw-test
```

### 4. 유사도 검사(선택)

```bash
cd script
python3 similarity_report.py ../docker/data/hw-test -o ../docker/reports/hw-test/similarity.json
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
* GitHub Classroom API 연동
* 부동소수/정규식 출력 비교
* 웹 UI 대시보드 시각화
