# 이슈 #168 체크리스트 작업 규칙

이 디렉터리는 이슈 #168의 노드·실패·시나리오 체크리스트를 Claude와 Codex가 같은 형식으로 수정하기 위한 D 소유 작업 공간입니다.

## 정본과 범위

- `checklist.yaml`이 시나리오, 오류 코드, 다음 행동, 담당 확인, 구현 상태, 근거의 정본입니다.
- B의 교시·실측·파라미터 값은 복사하지 않습니다. `config/*.yaml`, `params/skills.yaml` 등 담당자 정본의 경로와 필요한 키만 참조합니다.
- 계약 값은 `contracts/`, 태스크 구현은 `tasks/`, 온톨로지는 `knowledge/`의 원본을 참조합니다.
- mock·실물 시험 결과, 원위치 오차, 저속 설정, 운전자·안전 감시자 증적은 Google Sheet에만 기록합니다.
- `params/skills.yaml`은 현재 checkout에 없으므로 값이나 존재 여부를 추정하지 말고 `not_in_current_checkout` 상태를 유지합니다.

## 확인·변경 절차

1. `docs/README.md`에서 관련 문서를 찾고 `docs/requirements.md`의 연결된 ID와 P2 범위만 확인합니다.
2. 이슈 #168 본문과 새 댓글, 연결된 PR·이슈를 읽습니다.
3. `checklist.yaml`에서 해당 노드 또는 시나리오만 최소 변경합니다.
4. B·C·E 제안은 담당자별 `confirmation`으로 분리합니다. 합의되지 않은 코드·값은 만들지 않고 `pending`, `approval_pending`, `[오류 코드 확정 필요]`로 둡니다.
5. 구현 여부는 원본 파일이나 병합된 PR로 확인합니다. 댓글의 예정 표현만으로 `implemented`로 바꾸지 않습니다.
6. 변경 근거를 `source_catalog`에 등록하고 항목의 `sources`에서 참조합니다.
7. 변경 후 `--validate`를 실행하고, 담당자 변경이 병합된 뒤에는 `--dry-run`으로 시트 변경 예정 범위를 확인합니다.

## Claude·Codex 공통 규칙

- 먼저 `checklist.yaml`과 수정 대상의 `sources`만 읽고, 관련 없는 문서를 한꺼번에 읽지 않습니다.
- 기술 값을 YAML에 복제하지 않습니다. 원본 경로·키·이슈 댓글·PR 번호만 남깁니다.
- `confirmation`, `implementation`, `decision`을 서로 대신하지 않습니다. 담당자 동의는 구현 완료나 시험 통과를 뜻하지 않습니다.
- B·C·E 소유 파일을 D 체크리스트 작업의 부수 변경으로 수정하지 않습니다.
- 미확정 오류 코드나 임계값을 임의로 명명하거나 채우지 않습니다.
- Google Sheet의 시험 결과와 현장 증적을 `checklist.yaml`로 역동기화하지 않습니다.
- 사용자 요청 없이 push하거나 PR을 만들지 않습니다.

## 담당자 전달 방식

파일을 별도 공동 경로로 복사하지 않습니다. 담당자에게 저장소의 PR 또는 커밋 링크와 변경한 ID 목록을 전달합니다. 담당자는 같은 브랜치를 검토하거나 자신의 브랜치에 커밋을 가져옵니다.

## 검증과 동기화

세 명령만 사용합니다.

```bash
python tools/sync_issue168_checklist.py --validate
python tools/sync_issue168_checklist.py --dry-run
python tools/sync_issue168_checklist.py --apply
```

- `--validate`: 필수 필드, ID, 상태값, 오류 코드, 근거 참조와 저장소 파일 경로를 검사합니다.
- `--dry-run`: 인증이 있으면 현재 시트와 비교한 셀별 변경 내용을 출력하고, 인증이 없으면 관리·보호 열 계획만 출력합니다. 시트는 수정하지 않습니다.
- `--apply`: `--dry-run`과 같은 비교를 수행한 뒤 변경된 자동 관리 셀만 반영합니다.

시나리오 표의 자동 관리 열은 `ID`, `상황`, `노드·오류 코드`, `C Runner 다음 행동`, `B 확인`, `C 확인`, `E 확인`, `결정 상태`입니다. `mock 결과`, `실물 결과`, `증적 링크`, `판정`, 측정값과 현장 증적을 포함한 나머지 열은 쓰기 요청에 포함하지 않습니다.

라이브 미리보기와 적용에는 저장소 밖의 서비스 계정 인증 파일을 지정합니다.

```bash
export ISSUE168_GOOGLE_CREDENTIALS=/보안경로/credentials.json
```

서비스 계정에는 이슈 #168 시트만 필요한 권한으로 공유해야 합니다. 인증 파일은 저장소에 복사하거나 커밋하지 않습니다.

적용이 성공하면 `00_진행현황!A9:D9`에 마지막 YAML 동기화 commit SHA와 KST 시각을 기록합니다. 이 메타데이터 영역도 D가 관리하며 시험 결과·증적 영역과 분리합니다.

## 현재 단계

`checklist.yaml`에서 Google Sheet로만 동기화합니다. 검증, 미리보기, 보호 열을 제외한 적용과 동기화 SHA·시각 기록을 구현했습니다.
