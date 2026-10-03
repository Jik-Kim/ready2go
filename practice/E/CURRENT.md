# CURRENT — E 고희태

- **담당**: 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 (조장) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-03

## 지금 상태
- #8의 실측/외접박스 표 11종·12개를 world 원본에 반영했습니다. 등록 물품 전체가 P1 단일 요청 대상이며 최종 파지 승인은 별도입니다. [문서]
- 파지 힘은 item_grasp.yaml의 null, 승인 상태는 false로 두었습니다. 미확정 설정 거절 함수 제공과 B/C 실물 경로 연결은 구분합니다. [문서]
- 공용 ontology/interfaces/hardware/README와 연관 예시·프리셋을 갱신했습니다. 높이 1.0 cm 일괄 변경이나 실물 위치·시험 성공을 임의 확정하지 않았습니다. [문서]
- 온톨로지 작성 원본을 classes·world·스킬 파일로 분리하고, `robot_ontology.jsonld`는 공통 context와 참조 목록으로 구성했습니다. [문서]
- E 로더가 분리 파일·초기 상태 프리셋·장소 YAML을 연결하고 기존 `classes/world/state/skills` 조회 구조를 반환합니다. [문서]
- 장소 설정의 정본은 `config/places.yaml`이며 공통 식별자로 결합합니다. 미측정 null은 유지합니다. [문서]
- 기존 복합 스킬 이름을 `handover_with_unpack`으로 변경했습니다. 태스크 경로와 동작 정의는 유지했습니다. [문서]
- 초기 상태 프리셋은 `knowledge/snapshots/initial_state.json` 하나로 유지합니다. 실제 상태 확인·적용·저장은 Runner 책임입니다. [문서]

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 장소 설정 정본 | `config/places.yaml` | [문서] 사용자 합의 |
| 연결 식별자 | `world.places`와 YAML의 동일 장소 키 | [문서] 사용자 합의 |
| 복합 스킬 이름 | `handover_with_unpack` | [문서] 사용자 지정 |

## 막힌 점 · 필요한 도움
- TODO(A): config/vision_stub.yaml의 구 watch/wallet 참조는 PR #45 샘플로 반영하고 공통 로더 연결을 해야 합니다. 분리 브랜치에서 클래스 번호 파일은 A가 생성합니다. [문서]
- TODO(A·B): size_m 로컬 축/yaw 기준과 lip_balm 외접박스 높이 20.0 mm/이전 20.2 mm 보고의 차이를 확인해야 합니다. [문서]
- TODO(B·E): 물품별 힘·파지점·반복성·높이 기준/지우개 예외 승인; TODO(C): require_grasp_settings와 실제 실행·TTS·인스턴스 상태 연결. [문서]
- TODO(A 김병직): `tools/yolo/build_dataset.py:class_names()`의 단일 JSON 직접 읽기를 공통 로더 또는 `world.jsonld` 조회로 변경해야 합니다. 분리 후 기존 방식은 `world` 키를 찾지 못합니다. [문서]
- TODO(C 이영훈): 태스크 스킬 호출·실패 상태 계약 및 로그의 전체 구성 해시 기록 연결이 필요합니다. [문서]
- TODO(B 서동권): 접근 동작 책임과 미측정 설정의 실행 전 검사 계약 확인이 필요합니다. [문서]

## 다음 할 일
- [ ] A의 데이터셋 도구 인계 반영 후 연결 확인
- [ ] C·B와 실행 계약 보완 사항 확정

## 철회한 결론
- 진입점 JSON을 직접 읽으면 전체 정의가 나온다는 기존 가정은 파일 분리 후 사용할 수 없습니다. [문서]
