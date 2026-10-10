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
| [`initial_state.json`](../knowledge/snapshots/initial_state.json) | 실제 상태와 대조한 뒤 적용할 초기화용 예시 프리셋 |
| [`places.yaml`](../config/places.yaml) | 장소 좌표계·실측 치수·이동 거리·설정의 정본 |
| [`item_grasp.yaml`](../config/item_grasp.yaml) | 물품별 파지 힘과 검증 승인 상태의 정본 |

`ready2go_knowledge.core.ontology.load()`는 manifest의 상대 경로를 따라 파일을 읽고 `classes/world/state/skills`로 반환합니다. `sources`는 프로젝트 로더 규칙이며 JSON-LD 표준의 자동 import가 아닙니다. 장소와 파지 설정은 동일 식별자로 결합하며 미측정 `null`을 보존합니다. 상세 사용법은 [knowledge/README.md](../knowledge/README.md)를 참조합니다. [문서]

**현재 분리 형식에서 검사하는 항목**: 필수 sources와 객체 형식, JSON/YAML 중복 키, 중복 스킬 ID, 장소 설정 누락·중복, 물품과 파지 설정 ID 일치, 양수 유한값 3개의 `size_m`, 파지 설정 형식·값, 물품·장소의 class 참조, 초기 located_in의 물품·장소 참조, 목록의 물품 참조입니다. 기존 단일 파일 호환 경로는 JSON을 읽어 그대로 반환하며 이 전체 검사를 수행하지 않습니다. [문서]

**현재 수행하지 않는 검사**: 스킬과 실행 구현의 대응, 모든 조건의 상태 경로, 전체 오류 코드, 파라미터 매핑의 완전성 검사입니다. 이러한 검사를 근거로 Runner 시작을 차단하는 기능도 E 로더에 없습니다. 향후 클래스 추론·정합성 기능의 요구사항은 [FR-ONT-03](requirements.md#fr-ont-03)에 따르며, 구현 범위는 별도 확정해야 합니다. [문서]

스킬 파라미터가 원자 동작과 같은 대상을 뜻하면 같은 이름을 사용하고, 스킬 수준의 `item/from/to`는 `expand`에서 원자 동작 파라미터로 명시적으로 매핑합니다. 현재 데이터에 `hold/verify`가 있어도 자동 관측 검증 구현을 의미하지 않습니다. 문자열 verify의 관측값·임계값 출처·평가 방법과 접근 동작 책임은 B·C·E 계약 보완 사항입니다. [문서]

### P1 공통 pick 실행 연결

[문서] [공통 pick](../knowledge/skills/pick.jsonld)은 기존 manifest 등록·`item/from`·pre/hold/effect/verify를 유지합니다. 정식 [find_item 태스크](../tasks/find_item.json)의 `s5.1`에서 탑뷰 이동 → 최초 관측 `scan` → B `nudge_object` → 탑뷰 이동 → 재관측으로 스킬 로컬 `scan` 갱신 → `pick_object(target=$scan.target)`를 전개합니다. 최초/재관측 응답은 각각 e2/e5 기록에 보존하며 e6은 갱신된 두 번째 응답을 사용합니다. 끌기 예상값 `nudge.target_after`는 집기에 사용하지 않습니다. P1 공간 판단은 B의 기존 코드가 담당하며 충분하면 `pushed=false`로 이동 없이 성공합니다. 선형 전개를 유지하므로 이 경우도 재관측합니다. B pick의 벽 간섭 검사는 유지합니다. 독립 스킬·내부 분기·Runner 확장·새 비전 clearance 필드는 추가하지 않습니다.

[문서] 현재 main Runner의 null 참조 차단(`VAR_NULL`)과 하위 실패 전파를 사용합니다. 최초/재관측 target이 null이면 각각 nudge/pick을 보내지 않고, 전체 pick 성공에만 effect를 적용합니다. 탑뷰 이동 뒤에는 기존 YAW_INVALID 재시도도 억제됩니다. hold/verify 보존은 P2 사후 관측 검증 구현이 아닙니다. [Knowledge 연결·인계](../knowledge/README.md#p1-공통-pick의-벽-인접-끌기재관측-연결)에 호출 순서·오류 선언·모의 테스트 한계를 기록합니다.

[문서] 기준은 P1 FR-ONT-01·FR-PLN-01 및 [FR-ACT-05/AC-ACT-05](requirements.md#fr-act-05)입니다. [AC-ACT-05](requirements.md#ac-act-05)의 실물 성공률은 미측정입니다. C 호출열/횟수 검사는 PR #130, pick 시간 예산은 PR #164로 반영됐으며 현재 값은 [태스크 원본](../tasks/find_item.json)에서 확인합니다. 후속 통합에서 B는 배포 SHA·끌기 no-op/실패·탑뷰/wall guard, A는 실제 재관측 새 프레임·좌표를 확인해야 합니다. finally는 기존 안전 조건에 따르며 ESTOP/잠금에서 자동 닫기·홈을 단정하지 않습니다. 과거 시연 전용 온톨로지·집기 원본은 제거했으며 현재 실행 기준은 공통 manifest와 pick입니다. 정식 find_item과 점검용 p1_demo_eraser 태스크는 모두 공통 pick을 호출합니다. 과거 실측 로그·fixture·변경 이력은 보존하지만 현재 실행 기준이나 재관측 검증 완료의 근거로 사용하지 않습니다. P2부터의 공간 판단 주체는 미확정이며 [이슈 #120](https://github.com/Jik-Kim/ready2go/issues/120) 후속 합의 대상으로 남깁니다. FR-ACT-05의 밀기 표현과 실제 누르고 끄는 구현의 문구 차이는 정본 담당 인계이며 이번에 요구사항/계약을 바꾸지 않습니다.

### 물품 정의·치수·요청 범위 (P1, #8 반영)

- **원본**: `knowledge/world.jsonld`의 `world.items`. 진입점 `knowledge/robot_ontology.jsonld`에는 파일 참조만 있으므로 `ready2go_knowledge.core.ontology.load()`로 읽음. 장소 설정은 `config/places.yaml`, 파지 힘·최종 검증 여부는 `config/item_grasp.yaml`에서 같은 식별자로 연결함.
- **요청 범위**: [FR-INT-02·물품 정책](requirements.md#item-policy)을 참조함. 현재 `commute_set`은 예시 데이터이며 실제 시연 목록 확정·음성 연결의 근거가 아님.
- **치수·분류·역할 의미**: [물품 정책](requirements.md#item-policy)을 참조함. 현재 `world.items`는 #8 실측 치수와 #6·#61 정렬을 반영하며 `class`·`roles`를 제공함. 좌표·pose 형식은 실행 원본과 [interfaces.md](interfaces.md)를 대조함. 로더의 참조 검사와 실제 A/B 소비 경로 연결 완료는 구분함. [문서]
- **인스턴스**: 의미는 [관측 정책](requirements.md#observation-policy)을 참조함. 현재 world는 클래스 키로 조회하고 A가 관측 ID를 제공함. 초기 위치 프리셋은 개별 인스턴스 추적 구현이 아니며 A/C 상태 계약과 실제 연결은 후속 확인 사항임.
- **파지 설정**: 등록·인식·라벨링과 실물 파지 승인은 구분함. 미확정 `grip_force`는 YAML의 `null`, `grasp_verified`는 `false`로 둠. 임의 기본 힘·임계값을 넣지 않음. 로더는 이를 물품 조회 결과에 제공하며 `require_grasp_settings(onto, item)`은 미확정 설정을 거절함. 이 함수를 **B/C의 실제 파지·밀기·복구 경로에 연결하는 작업은 인계 사항**으로, 이번 변경만으로 실행 차단이 자동 적용되는 것은 아님.
- **근거·결정 기록**: [#8](https://github.com/Jik-Kim/ready2go/issues/8)에 실측·시험·B/E 채택 근거를 기록하고, 선정 기준·물품별 검증 상태는 [hardware.md 2.3](hardware.md#23-물품-선정-기준-day-2-실물-파지-테스트로-확정), 인터페이스 의미는 [interfaces.md](interfaces.md)에서 공유함. 삭제된 `decisions.md`를 결정 기록 위치로 사용하지 않음.

### 7.6 확장 정의와 연결 경계

기존 복합 스킬 이름은 `handover_with_unpack`이며 참조 태스크는 `tasks/find_with_unpack.json`입니다. P2 목표·재식별·복구 기준은 [FR-ACT-04](requirements.md#fr-act-04)·[가림 정책](requirements.md#occlusion-policy)을 참조합니다. 현재 참조 태스크는 이전 외부 트레이 예시이며 내부 이동 계약 반영·실행 검증은 [domain.md 인계표](domain.md)를 따릅니다. 옮긴 장애물의 located_in은 서랍 그대로이고 pose 추적/복구 기록은 C·E 합의가 필요합니다. staging_tray 정의는 소비자 잔존참조 때문에 이번에 삭제하지 않습니다. 등록된 데이터가 P1 실물 경로에서 가림 탐색을 실행할 수 있다는 뜻은 아닙니다. [문서]

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

[문서] handover 확인 후보는 destination=handover_zone만 수용하며 질문에는 전달 트레이 이름을 사용합니다. 기대물품 ID는 현재 world의 name_ko 대응표로 표시하고 표시명이 없으면 질문/후보를 만들지 않습니다. drawer/LIFO는 거절합니다. 이 대응표 공급 역시 후속 운영 adapter가 검증해야 합니다.
