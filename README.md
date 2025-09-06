# C Grader

> C code compile and grading software

## 개요

이 프로젝트는 학생들이 GitHub에 제출한 C 과제를 자동으로 가져와 **컴파일 → 테스트케이스 실행 → 채점 결과 리포트 생성**까지 한 번에 처리하는 도구입니다.
다음과 같은 기능들을 제공합니다:

* GitHub에서 학생별 제출 코드를 자동으로 크롤링
* 특정 시한(`limit`) 이전 커밋까지만 인정하여 채점
* Docker 컨테이너 내부에서 GCC로 안전하게 컴파일 및 실행
* 테스트케이스(JSON) 기반 자동 채점
* 학생별 JSON 리포트 + 전체 요약 테이블 생성
* 표/엑셀에서 복사한 제출현황 텍스트를 student\_map.json으로 변환

---

## 디렉터리 구조 예시

```
.
├── build.sh                 # Docker 이미지 빌드 스크립트
├── dockerfile               # 채점 환경 Dockerfile
├── run.sh                   # 크롤링 + 채점 전체 실행 스크립트
├── run_tests.py             # 단일 소스코드 채점 러너
├── fetch_and_stage.py       # student_map.json 기반 GitHub 코드 수집
├── make_student_map.py      # 제출현황 텍스트 → student_map.json 변환
├── data
│   └── hw-test
│       ├── tests.json       # 테스트케이스 (입력/출력 기대값)
│       └── student_map.json # 학생 ID, URL, limit 정보
├── reports
│   └── hw-test              # 학생별 리포트(JSON) 저장
└── README.md
```

---

## 주요 구성요소 설명

### 1. Dockerfile

* Debian slim 기반
* `build-essential`(gcc, libc-dev 등) + Python3 설치
* 기본 실행 엔트리포인트는 `python3 run_tests.py`
* 컨테이너 내부에서만 채점을 수행하므로 안전합니다.

### 2. build.sh

```bash
#!/usr/bin/env bash
docker build -t c-stdin-tester -f dockerfile .
```

* 채점용 Docker 이미지를 빌드합니다.

### 3. run\_tests.py

* 단일 C 소스(`main.c`)와 테스트 JSON(`tests.json`)을 입력받아:

  1. GCC로 컴파일
  2. 각 테스트케이스(stdin 입력 제공) 실행
  3. 프로그램 출력과 기대 출력 비교
  4. 결과 요약 및 JSON 리포트 작성
* 옵션

  * `--src`: 소스 파일 경로
  * `--tests`: 테스트케이스 JSON
  * `--report`: 결과 리포트 파일(JSON)
  * `--summarize-dir`: 다수 리포트를 요약 테이블로 출력

테스트 JSON 예시:

```json
[
  {"name": "case1", "stdin": "1 2\n", "expected": "3\n"},
  {"name": "case2", "stdin": "10 20\n", "expected": "30\n"}
]
```

### 4. run.sh

* 지정한 과제 폴더(`data/hw-test`)와 `student_map.json`을 입력받아:

  1. `fetch_and_stage.py` 실행 → 각 학생의 main.c 다운로드
  2. Docker 컨테이너에서 `run_tests.py` 실행 → 학생별 채점
  3. `reports/hw-test/`에 JSON 리포트 생성
  4. 전체 요약 테이블 출력
* 실행 예:

```bash
./run.sh hw-test data/hw-test/student_map.json
```

### 5. fetch\_and\_stage.py

* `student_map.json`에 따라 GitHub에서 코드를 내려받습니다.
* 기능:

  * `blob`/`raw` URL을 `raw.githubusercontent.com` 주소로 변환
  * 파일명이 한글/공백/특수문자일 경우 안전하게 인코딩
  * `limit` 값이 있으면 GitHub API로 해당 시각 이전 마지막 커밋을 찾아서 그 버전만 다운로드
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

* 제출현황 텍스트(엑셀에서 복사한 표 형태/기본적으로 계명대학교 과제평가의 `엑셀 다운로드` 포맷과 일치)에서 학생 ID와 GitHub URL을 추출하여 `student_map.json` 생성.
* URL이 전각문자(`ＨＴＴＰＳ ://...`)로 깨져도 자동 정규화.
* `.c`/`.cpp` 파일 링크만 우선 선택.
* 실행 예:

```bash
python3 make_student_map.py table.txt \
  --limit 2025-09-09T00:00:00Z \
  --only-submitted \
  --pretty \
  -o data/hw-test/student_map.json
```

### 7. student\_map.json 형식

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

## 채점 프로세스 흐름

1. 교수자가 제출현황 표를 엑셀 → 텍스트로 추출
2. `make_student_map.py`로 student\_map.json 생성
3. `run.sh` 실행 시 `fetch_and_stage.py`가 GitHub에서 소스를 다운로드

   * `limit` 이전 커밋만 인정
4. Docker 컨테이너 안에서 `run_tests.py`가 채점 수행
5. 학생별 리포트(JSON) 저장 + 전체 요약 출력

---

## 보안 고려

* 학생 코드는 반드시 **Docker 컨테이너 내부에서만 실행**
* 필요 시 `--network=none --memory=256m --cpus=1.0` 등 옵션으로 실행 자원 제한
* 실행 타임아웃 기본 2초, 무한루프 방지

---

## 확장 아이디어

* 결과를 CSV/엑셀로 내보내기
* GitHub Classroom API 연동
* 테스트케이스 정규식/부동소수 비교 지원
* UI 대시보드로 시각화

---

## 실행 요약

```bash
# 1. Docker 이미지 빌드
./build.sh

# 2. student_map.json 생성
python3 make_student_map.py table.txt --limit 2025-09-09T00:00:00Z --only-submitted --include-nonfile -o data/hw-test/student_map.json

# 3. 채점 실행
./run.sh hw-test data/hw-test/student_map.json
```