# 로봇 온톨로지 · 파일 구조와 상태 계약

> 의미·정책·책임·Phase·수용 기준은 [requirements.md](requirements.md)에만 정의합니다. 이 문서는 데이터 구조, 현재 E 로더의 기능, 담당별 연결 사항을 설명합니다. 시연 예시는 구현 완료의 근거로 사용하지 않습니다.

## 7. 로봇 온톨로지 및 JSON 규격

### 7.5 파일 역할과 현재 로더

[FR-ONT-01](requirements.md#fr-ont-01)의 물품·장소·상태·스킬을 하나의 조회 구조로 정의합니다. 작성 파일을 분리하되 `robot_ontology.jsonld`를 전체 구성의 진입점으로 사용합니다. [문서]

| 원본 | 역할 |
| :--- | :--- |
| [`robot_ontology.jsonld`](../knowledge/robot_ontology.jsonld) | 공통 `@context`와 `sources` 참조 목록 |
| [`classes.jsonld`](../knowledge/classes.jsonld) | 종류와 계층 정의 |
| [`world.jsonld`](../knowledge/world.jsonld) | 물품·목록·장소 정의 |
| `knowledge/skills/*.jsonld` | 입력·사전 조건(`pre`)·전개(`expand`)·성공 후 결과(`effect`)·오류 정의 |
| [`initial_state.json`](../knowledge/snapshots/initial_state.json) | 기본 P1 초기화용 예시 프리셋 |
| `knowledge/snapshots/p2_s1.json`·`p2_s2.json`·`p2_s3.json` | 승인된 P2 시작 배치; C 선택 소비는 미연결 |
| [`places.yaml`](../config/places.yaml) | 장소 좌표계·실측 치수·이동 거리·설정의 정본 |
| [`item_grasp.yaml`](../config/item_grasp.yaml) | 물품별 파지 힘과 검증 승인 상태, 실제로 잡은 폭(선택, B 실측)의 정본 |

`ready2go_knowledge.core.ontology.load()`는 manifest의 상대 경로를 따라 파일을 읽고 `classes/world/state/skills`로 반환합니다. `sources`는 프로젝트 로더 규칙이며 JSON-LD 표준의 자동 import가 아닙니다. 장소와 파지 설정은 동일 식별자로 결합하며 미측정 `null`을 보존합니다. 선택 입력 `snapshot`은 상태 파일만 대체하며 생략하면 기본 P1 상태를 유지합니다. 활성 10종·고정 학습 11종의 구분, 장면 위치와 미배치 물품, C 기동/reset 미연결은 [knowledge/README.md](../knowledge/README.md#p2-시작-배치-선택--e-구현c-연결-대기)를 참조합니다. [문서]

**현재 분리 형식에서 검사하는 항목**: 필수 sources와 객체 형식, JSON/YAML 중복 키, 중복 스킬 ID, 장소 설정 누락·중복, 물품과 파지 설정 ID 일치, 양수 유한값 3개의 `size_m`, 파지 설정 형식·값, 물품·장소의 class 참조, 초기 located_in의 물품·장소 참조, 목록의 물품 참조입니다. 기존 단일 파일 호환 경로는 JSON을 읽어 그대로 반환하며 이 전체 검사를 수행하지 않습니다. [문서]

**현재 수행하지 않는 검사**: 스킬과 실행 구현의 대응, 모든 조건의 상태 경로, 전체 오류 코드, 파라미터 매핑의 완전성 검사입니다. 이러한 검사를 근거로 Runner 시작을 차단하는 기능도 E 로더에 없습니다. 향후 클래스 추론·정합성 기능의 요구사항은 [FR-ONT-03](requirements.md#fr-ont-03)에 따르며, 구현 범위는 별도 확정해야 합니다. [문서]

스킬 파라미터가 원자 동작과 같은 대상을 뜻하면 같은 이름을 사용하고, 스킬 수준의 `item/from/to`는 `expand`에서 원자 동작 파라미터로 명시적으로 매핑합니다. 현재 데이터에 `hold/verify`가 있어도 자동 관측 검증 구현을 의미하지 않습니다. 문자열 verify의 관측값·임계값 출처·평가 방법과 접근 동작 책임은 B·C·E 계약 보완 사항입니다. [문서]

### P1 공통 pick 실행 연결

[문서: E-PICK-CONDITIONAL-NUDGE-20261013-01] [공통 pick](../knowledge/skills/pick.jsonld)은 manifest·이름·`item/from`·pre/hold/effect/verify·errors를 유지하고 expand만 조건부 흐름으로 바꿉니다. 같은 서랍 탑뷰 → 새 관측 `scan` → 전체 scan을 함께 전달한 집기를 먼저 실행합니다. `fallback.next_on=[WALL_TOO_CLOSE]`에 해당하는 움직임 전 거부만 넛지 → 탑뷰 → 새 `scan` 관측 1회 → 새 target/같은 전체 scan 집기로 진행합니다. 직접 성공 때 skill 관측은 1회, WALL 대안은 2회이며 nudge no-op도 대안의 재관측을 생략하지 않습니다. target_after·needed·plan_code·새 스킬·자동 반복은 쓰지 않습니다. B 접근/그리퍼/drag_down·place 책임은 유지합니다.

[문서] 실제 C #263/#269의 자동 하위 ID·fallback 오류 제한·부모 timeout/취소·로컬 scope·넛지 뒤 새 관측 출처 검사를 사용합니다. 최초/재관측 null은 VAR_NULL로 차단하고 다른 거부·움직임 불확실·nudge/관측 실패·정지는 뒤 집기를 보내지 않습니다. effect는 기존 전체 성공 뒤에만 적용하며 hold/verify는 보존 선언입니다. 자세 중복 억제와 전체 scan의 유효성은 별개이며, run/대상/서랍·stop/resume/불확실 이동에 따른 scan 재사용 자격은 C 미연결입니다. 이번 카드는 항상 새 관측을 받아 #245 전체 재사용 완료로 보고하지 않습니다.

[문서] 기준은 P1 [FR-ONT-01](requirements.md#fr-ont-01)·[FR-PLN-01](requirements.md#fr-pln-01)·[FR-ACT-05/AC-ACT-05](requirements.md#fr-act-05), P2 연결은 [FR-PLN-02](requirements.md#fr-pln-02)·[FR-ACT-04](requirements.md#fr-act-04)입니다. 현재 호출열·E 실제 카드 시험·C/B 문서와 회귀 인계·실물 미검증은 [Knowledge 연결](../knowledge/README.md#p1-공통-pick의-벽-인접-끌기재관측-연결)을 참조합니다. 과거 #130의 6단계 검사와 #164 시간 예산을 이번 실물 성공이나 유효 scan 재사용 증거로 전용하지 않습니다.

### 물품 정의·치수·요청 범위 (P1, #8 반영)

- **원본**: `knowledge/world.jsonld`의 `world.items`. 진입점 `knowledge/robot_ontology.jsonld`에는 파일 참조만 있으므로 `ready2go_knowledge.core.ontology.load()`로 읽음. 장소 설정은 `config/places.yaml`, 파지 힘·최종 검증 여부는 `config/item_grasp.yaml`에서 같은 식별자로 연결함.
- **요청 범위**: [FR-INT-02·물품 정책](requirements.md#item-policy)을 참조함. 현재 `commute_set`은 예시 데이터이며 실제 시연 목록 확정·음성 연결의 근거가 아님.
- **치수·분류·역할 의미**: [물품 정책](requirements.md#item-policy)을 참조함. 현재 `world.items`는 #8 실측 치수와 #6·#61 정렬을 반영하며 `class`·`roles`를 제공함. 좌표·pose 형식은 실행 원본과 [interfaces.md](interfaces.md)를 대조함. 로더의 참조 검사와 실제 A/B 소비 경로 연결 완료는 구분함. [문서]
- **인스턴스**: 의미는 [관측 정책](requirements.md#observation-policy)을 참조함. 현재 world는 클래스 키로 조회하고 A가 관측 ID를 제공함. 초기 위치 프리셋은 개별 인스턴스 추적 구현이 아니며 A/C 상태 계약과 실제 연결은 후속 확인 사항임.
- **파지 설정**: 등록·인식·라벨링과 실물 파지 승인은 구분함. 미확정 `grip_force`는 YAML의 `null`, `grasp_verified`는 `false`로 둠. 임의 기본 힘·임계값을 넣지 않음. 로더는 이를 물품 조회 결과에 제공하며 `require_grasp_settings(onto, item)`은 미확정 설정을 거절함. 이 함수를 **B/C의 실제 파지·밀기·복구 경로에 연결하는 작업은 인계 사항**으로, 이번 변경만으로 실행 차단이 자동 적용되는 것은 아님.
- **근거·결정 기록**: [#8](https://github.com/Jik-Kim/ready2go/issues/8)에 실측·시험·B/E 채택 근거를 기록하고, 선정 기준·물품별 검증 상태는 [hardware.md 2.3](hardware.md#23-물품-선정-기준-day-2-실물-파지-테스트로-확정), 인터페이스 의미는 [interfaces.md](interfaces.md)에서 공유함. 삭제된 `decisions.md`를 결정 기록 위치로 사용하지 않음.

### 7.6 확장 정의와 연결 경계

기존 복합 스킬 이름은 `handover_with_unpack`이며 참조 태스크는 `tasks/find_with_unpack.json`입니다. P2 목표·재식별·복구 기준은 [FR-ACT-04](requirements.md#fr-act-04)·[가림 정책](requirements.md#occlusion-policy)을 참조합니다. 현재 참조 태스크는 내부 이동·LIFO 복구·aside 및 RESTORE_INCOMPLETE 경로를 포함하며 실제 연결·실물 검증은 [domain.md 인계표](domain.md)를 따릅니다. aside는 원위치 복구 완료가 아닙니다. 옮긴 장애물의 located_in은 서랍 그대로이며 pose 추적/복구 검증은 별도입니다. staging_tray는 초기 open에서만 제외하고 world·설정 정의는 소비자 잔존참조 때문에 유지합니다. 등록된 데이터가 P1 실물 경로에서 가림 탐색을 실행할 수 있다는 뜻은 아닙니다. [문서]

자동 계획은 [FR-PLN-02](requirements.md#fr-pln-02), 복합 작업 추가는 [FR-PLN-03](requirements.md#fr-pln-03), 목록·분류 조회는 [FR-ONT-03](requirements.md#fr-ont-03)에 따릅니다. 스킬 파일과 sources 등록만으로 음성 프롬프트·플래너·태스크 레지스트리에 자동 반영된다고 보장하지 않습니다. 담당 모듈의 연결 확인이 필요합니다. 계획 설계는 [planner.md](planner.md)를 참조합니다. [문서]

### 7.8 상태 계약과 Phase별 연결

- 상태는 `state[predicate][subject] = value` 형태입니다. 초기 프리셋을 읽는 것과 실제 로봇 상태를 확인·관리하는 것은 별개입니다. 현재 상태·로그 관리 책임은 Runner(C)에 있습니다. [문서]
- [FR-PLN-01](requirements.md#fr-pln-01)의 현재 구현: E core는 조건·효과 함수를 제공하며 Runner가 실행 경로에서 호출합니다. 로더만의 검사와 실행 경로 검사를 구분합니다. [문서]
- P2의 사후 관측 verify는 [FR-ONT-02](requirements.md#fr-ont-02), P3의 관측 불일치 처리는 [FR-REC-01](requirements.md#fr-rec-01)에 따릅니다. 현재 문서나 데이터의 존재로 구현 완료를 판단하지 않습니다. [문서]
- 중간 실패 시 실제 상태·확인 불가 상태, 인스턴스별 위치, hold 평가, 상태 발행·지속성은 담당 코드와 계약을 확인해야 합니다. 실행·로그 설계는 [runner.md](runner.md)를 참조합니다. [문서]

### 7.9 그래프·선택적 확장

과거 물품과 시연 배치에 맞춘 그래프는 현재 world·상태의 근거로 사용하지 않습니다. 현재 문서 본문에서는 제외하며, 필요할 때 확정된 원본 데이터로 다시 작성합니다. PDDL 내보내기와 외부 플래닝 프레임워크는 선택적 검토 사항이며 현재 구현 범위에 포함하지 않습니다. [문서]

### #43 사후 검증 선언·내부 후보의 현재 상태

[문서] 정책·완료 기준은 [verification-policy](requirements.md#verification-policy)·[FR-ONT-02](requirements.md#fr-ont-02)·[FR-LOG-02](requirements.md#fr-log-02)에 둡니다. manifest→로더→skills 문자열 보존→Runner 실행 성공 뒤 effect의 실제 연결을 대조했습니다. pick/place/close_drawer의 문자열을 정리했지만 현재 P1 effect 소비 경로는 보존합니다. open_drawer는 원문 유지입니다. E [skill_confirmation.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/skill_confirmation.py)는 동일 pick 관측과 handover 질문/최종 근거만 분류하며 동작·상태·로그·성공 TTS를 실행하지 않습니다. 현재 질문 객체와 run/step/목적지/기대물품을 결합하고, 장치/관측 오류·중단·TTS 실패·미정 대기는 성공 후보를 내지 않습니다. 실제 C evaluator/verify 대기/최종 effect/로그·A 재촬영·B 관측은 미연결입니다. 승인 전 구조화 verify/evaluator 형식은 추가하지 않았습니다.

[문서: 이번 내부 구현] place의 문자열 verify는 목적지 재촬영·서랍 top view·트레이 정상 미검출 사용자 근거의 구분을 선언합니다. 기존 JSON 자료형과 pre/hold/effect/expand는 유지합니다. E 내부 확인은 같은 절차의 횟수·종료 상태와 질문별 TTS/녹음/SDK/STT 증빙을 보존합니다. 선언의 존재로 서랍 관측 evaluator·복합 성공·C effect 차단이 연결됐다고 판단하지 않습니다. 복합 검증과 복구 수용 기준은 [verification-policy](requirements.md#verification-policy)·[AC-ACT-03](requirements.md#ac-act-03)을 참조하십시오.

[문서] handover 확인 후보는 destination=handover_zone만 수용하며 질문에는 전달 트레이 이름을 사용합니다. 기대물품 ID는 현재 world의 name_ko 대응표로 표시하고 표시명이 없으면 질문/후보를 만들지 않습니다. drawer/LIFO는 거절합니다. 이 대응표 공급 역시 후속 운영 adapter가 검증해야 합니다.

## #78 place 오류 선언 정합성

[문서] [모션 차단·놓침 후 새 실행 정본](requirements.md#halt-motion-policy)에 연결해 `knowledge/skills/place.jsonld`의 errors에 B가 현재 반환하는 `OBJECT_DROPPED`를 추가했습니다. 당시 errors 추가는 params/pre/hold/effect/expand/verify·manifest·로더를 보존했습니다. 이번 verify 선언 갱신은 위 #43 절을 참조하십시오. errors는 선언 데이터이며 Runner 잠금·정지·복구/재개를 실행하는 허용 목록이 아닙니다. pick의 `GRASP_FAILED`나 아직 확정되지 않은 place 센서 반환 목록은 변경하지 않습니다.

[문서·코드 대조: 2026-10-10] [PR #202](https://github.com/Jik-Kim/ready2go/pull/202) 병합 원본의 C `interpreter.HALT_MOTION_CODES`는 `OBJECT_DROPPED`·`SENSOR_INVALID`를 기존 `HALT_CODES`에 포함합니다. 해당 오류는 `ABORTED`·잠금으로 처리하며 finally는 비모션 허용 목록만 실행하고 새 요청을 거절합니다. 두 오류의 실행은 `resumable=True`여도 재개 대기로 보존하지 않습니다. 이는 E errors 선언과 별개의 C 구현이며 실제 로봇 정지·복구 완료의 증명이 아닙니다.

[미연결/인계] B `skill_server._do_place_object`의 handover 경로는 현재 `check_hold`의 센서 이상과 놓침을 구분하지 않고 보유 기억을 지우며 운반 오류를 반환합니다. 실제 오류 원인/보유 확실성·정지/신선 관측, C의 관측 기반 상태 동기화·안전한 잠금 해제·명시적 새 run 운영 연결은 후속입니다. `reset_state()`는 시작 상태 스냅샷을 복원하지만 잠금을 풀거나 실제 상태 일치를 검증하지 않습니다. [#78](https://github.com/Jik-Kim/ready2go/issues/78)·[#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 남은 B/C 협의·E 포함 2인 계약 승인·운영 adapter·실물 검증을 별도로 확인합니다.
