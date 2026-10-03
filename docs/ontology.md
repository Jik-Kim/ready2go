# 로봇 온톨로지 · 상태 추적 · 지식 그래프

> 관련 요구사항: [FR-ONT-01–03](requirements.md#fr-ont-01), [FR-PLN-01–03](requirements.md#fr-pln-01), [FR-REC-01](requirements.md#fr-rec-01). 온톨로지와 상태 추적의 구현 상세는 이 문서에서 다룹니다.

## 7. 로봇 온톨로지 및 JSON 규격 (일부)

### 7.5 로봇 온톨로지 (동작 · 상태 · 세계, JSON-LD)

강사 챌린지의 중심. 로봇이 **할 수 있는 동작(skills)**, **현재 상태(state)**, **다루는 세계(world)**를 하나의 온톨로지로 정의하고, 플래너·Runner·LLM 파서·로거가 같은 로더 조회 구조를 기준으로 동작함. 작성 파일은 역할별로 분리하며, `robot_ontology.jsonld`가 전체 구성의 진입점임.

> **진입점**: [`knowledge/robot_ontology.jsonld`](../knowledge/robot_ontology.jsonld) — `@context`와 `sources` 참조 목록.
> **작성 원본**: [`classes.jsonld`](../knowledge/classes.jsonld), [`world.jsonld`](../knowledge/world.jsonld), `knowledge/skills/*.jsonld`, [`initial_state.json`](../knowledge/snapshots/initial_state.json). 파일별 역할은 [`knowledge/README.md`](../knowledge/README.md).

* **로딩**: `ready2go_knowledge.core.ontology.load()`가 참조 파일을 읽어 `classes`·`world`·`state`·`skills` 구조로 반환함. `sources`는 프로젝트 로더 규칙이며 JSON-LD 표준의 자동 import가 아님.
* **장소 설정 정본**: [`config/places.yaml`](../config/places.yaml)의 장소 식별자를 `world.places`와 연결하고, 로딩 시 설정을 결합함. TF·치수·`max_travel_m`·`return_slot`·`slots`·처짐 설정은 YAML에만 작성함. `null`은 미측정 상태로 보존하며 실행 전에 준비 여부 확인이 필요함.
* **이름 변경**: 기존 `fetch_with_unpack` 등록은 `handover_with_unpack`으로 변경함. 태스크 파일 `tasks/find_with_unpack.json`과 내부 동작은 유지함.

* **classes / world**: 물품·리스트·장소의 지식 (기존 물품 지식 베이스는 여기로 통합). `lists.*.items`에 쓰인 키는 반드시 `world.items`에 정의되어야 함(로딩 시 검증).
* **state**: 로더 반환값은 초기화용 상태 프리셋이며 실제 로봇 상태를 확인한 결과가 아님. 실제 상태 확인 후 Runner가 적용하고 실행 중 **현재 상태**를 관리함. `상태[predicate][subject] = value` 한 가지 형태로 통일(예: `open.drawer_top`, `located_in.eraser`, `gripper.robot`). 서랍과 트레이를 `open` 하나로 다뤄 "집거나 놓을 수 있는 곳인가"를 단순하게 판단함.
* **skills**: 로봇 동작의 정의.
  * `primitive` 스킬: **실행 조건(`pre`)·실행 중 유지 조건(`hold`)·결과(`effect`)·관측 확인 기준(`verify`)·원자 동작 전개(`expand`)·발생 가능 에러**를 가짐. 조건·결과는 모두 `{subject, predicate, op, value}` 레코드 형식으로 통일. 플래너가 조합에 사용함.
  * `hold`는 스킬 실행 중 주기적으로 확인(예: 집는 동안 서랍이 열려 있어야 함). 깨지면 즉시 중단하고 `HOLD_VIOLATED` 기록.
  * `composite` 스킬: 7.3 같은 태스크 JSON을 하나의 스킬로 등록. 결과가 관측에 따라 달라지는(`effect: "sensing"`) 탐색형 작업은 플래너 조합 대상이 아니라 인텐트로 직접 호출함.
* 물품 `size_m`은 #8의 최신 치수 보고와 제공된 외접 박스 표로 갱신함. 미확정 파지 힘은 `config/item_grasp.yaml`에 두며 임의 예시값을 유지하지 않음. 장소 설정의 실측 여부·근거는 정본 `config/places.yaml`에서 관리하고, 미측정 값을 온톨로지 예시값으로 대체하지 않음.
* **원천은 JSON-LD, PDDL은 내보내기만**: 조건·결과 레코드는 PDDL의 술어 형식과 1:1로 대응하므로, 여유가 있으면 PDDL 내보내기 스크립트로 "표준 플래닝 언어와 호환"을 증빙함. PlanSys2·SkiROS2 같은 외부 프레임워크 도입은 향후 과제로 둠(ROS 2 Jazzy 지원·C++ 부담, 선행 사례 보고서 참고).
* **파라미터 이름 규칙**: 스킬 파라미터가 원자 동작 파라미터(7.1)와 같은 대상을 가리키면 **같은 이름**을 씀(예: `drawer_id`). 스킬 수준에서만 쓰는 개념(`item`, `from`, `to`)은 `expand`에서 원자 동작 파라미터(`search_target`, `region`, `location`)로 명시적으로 매핑하며, 정합성 검사(아래)가 매핑 누락을 잡아냄.
* **목적지 종류에 따른 자동 처리**: `place` 스킬은 `location: "$to"`만 넘기고, 목적지가 서랍이면 `place_object` 백엔드가 서랍 좌표계·z 보정을 자동 적용함(7.1 `place_object`). 원위치 복구처럼 정확한 자리가 필요하면 태스크 JSON에서 `pose` + `frame: "drawer"`를 직접 지정함(7.3 `f1.4`).
* **시작 시 정합성 검사**: 로딩 시 ① 모든 스킬에 실행 구현이 있고 그 역도 성립, ② 모든 조건이 존재하는 상태 경로를 참조, ③ 모든 에러 코드가 정의됨을 검증하고, 실패하면 Runner를 시작하지 않음.


### 물품 정의·치수·요청 범위 (P1, #8 반영)

- **원본**: `knowledge/world.jsonld`의 `world.items`. 진입점 `knowledge/robot_ontology.jsonld`에는 파일 참조만 있으므로 `ready2go_knowledge.core.ontology.load()`로 읽음. 장소 설정은 `config/places.yaml`, 파지 힘·최종 검증 여부는 `config/item_grasp.yaml`에서 같은 식별자로 연결함.
- **요청 범위**: P1은 등록된 물품 중 사용자가 요청한 단일 물품을 처리함. 시험 예시·초기 배치·`commute_set`으로 요청 가능한 물품을 제한하지 않음. 목록·분류 요청은 P3. `commute_set`은 참조 정합성을 유지한 P3 예시 데이터이며 실제 시연 목록 확정을 의미하지 않음.
- **치수 계약**: `size_m = [x 폭, y 길이, z 높이]`, 단위 m, 눕힌 상태의 물체 로컬 축 기준 외접 바운딩 박스. `yaw=0`이면 물체 로컬 x·y가 `pose.frame`의 x·y와 일치함. `yaw`는 해당 프레임 +z축 주위 회전(rad). A의 방향 추정과 B의 파지·밀기 계산을 이 계약에 맞춰 연결해야 함. 원통·원뿔도 최대 외곽을 포함하는 박스로 나타냄. **과거 예시 치수가 이 약속에 맞았다는 검증은 없음**. 이번 실측 보고에 맞춰 정정함.
- **분류와 역할은 별개**: `car_key`는 `Key`, `cover_plate`는 `Obstacle`, 나머지는 `Item`. YOLO의 `class` 문자열(예: `eraser`)은 온톨로지 분류 `Item`과 다름. 모든 11종에 `roles: ["request_target"]`를 부여하고 판에는 `occluder`도 부여함. 어떤 일반 물품도 배치에 따라 다른 물품을 가릴 수 있음. `Obstacle`이라는 분류가 사용자 요청을 금지하지 않음. 이번 목록에 인식만 하는 제외 물품은 지정하지 않음.
- **인스턴스**: `eraser`는 클래스 키 하나이며 물품 2개를 `world.items`에 중복 등록하지 않음. `eraser#1`·`eraser#2`는 A가 관측 시 부여함. 초기 상태의 클래스별 위치 프리셋은 개별 인스턴스 위치·추적을 구현한 것이 아님. 서로 다른 장소에 같은 클래스가 있으면 A·C의 인스턴스 상태 계약이 필요함.
- **파지 설정**: 등록·인식·라벨링과 실물 파지 승인은 구분함. 미확정 `grip_force`는 YAML의 `null`, `grasp_verified`는 `false`로 둠. 임의 기본 힘·임계값을 넣지 않음. 로더는 이를 물품 조회 결과에 제공하며 `require_grasp_settings(onto, item)`은 미확정 설정을 거절함. 이 함수를 **B/C의 실제 파지·밀기·복구 경로에 연결하는 작업은 인계 사항**으로, 이번 변경만으로 실행 차단이 자동 적용되는 것은 아님.
- **근거·결정 기록**: [#8](https://github.com/Jik-Kim/ready2go/issues/8)에 실측·시험·B/E 채택 근거를 기록하고, 선정 기준·물품별 검증 상태는 [hardware.md 2.3](hardware.md#23-물품-선정-기준-day-2-실물-파지-테스트로-확정), 인터페이스 의미는 [interfaces.md](interfaces.md)에서 공유함. 삭제된 `decisions.md`를 결정 기록 위치로 사용하지 않음.

### 7.6 새 작업 추가 = 온톨로지에 스킬 추가 (코드 수정 0줄)

* 새 작업은 `tasks/<이름>.json`(7.2 스키마)과 복합 스킬 정의 파일을 추가하고, 진입점 `sources.skills`에 해당 파일을 등록함. 파일에 `trigger`(인텐트 이름·예문)를 적으면 **LLM 인텐트 파서(6.4)의 프롬프트와 플래너에 자동 반영**되어 음성 명령까지 함께 추가됨.
* 새 원자 수준 능력은 `primitive` 스킬로 추가(예: "트레이 흔들어 정렬하기"). 기존 원자 동작의 조합으로 `expand`를 적을 수 있으면 역시 코드 수정이 필요 없음.

> **원본 파일**: [`tasks/return_items.json`](../tasks/return_items.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

> 위 예시의 `sequence`는 지면상 첫 스텝만 표기. 시연 2막(17.4)의 "정리해줘"가 이 방식의 증빙임.

### 7.8 상태 추적 규칙 (담당 C, 온톨로지 데이터 E)

* **Runner가 상태의 단일 관리자**. 스킬 실행 전 `pre`를 확인하고(`PRE_UNMET`이면 실행하지 않음), 실행 중 `hold`를 확인하며, 액션 성공 후 `verify` 관측이 통과해야 `effect`를 반영.
* **관측이 우선**: `inspect_region` 결과(물품 위치), `/drawers/state`(서랍), `/gripper/state`(그리퍼)가 상태와 다르면 **관측값으로 고치고 `STATE_MISMATCH`를 로그**에 남김. 1막의 차키 위치 자동 수정도 이 규칙으로 동작함.
* 현재 상태는 `/robot_state` 토픽(JSON)으로 계속 발행 → 시연 화면·Isaac Sim 트윈이 사용.
* 상태는 DB에 저장하여 작업 사이에 유지됨(2막에서 1막의 수정 결과 사용).

### 7.9 지식 그래프 (초안)

7.5 로봇 온톨로지를 그림으로 나타낸 초안. 그림은 과거 물품·시나리오 기준 초안이며 이번 물품 원본·현재 상태의 증빙이 아님. 새 목록과 시나리오가 확정되면 최종본으로 다시 그림(원본: 팀 공유 `지식 그래프_초안.pdf`).

**① 분류 계층(TBox)과 개체(ABox)** — 하위 클래스(실선), 개체의 종류(점선), 목록 구성. "귀중품 다 찾아줘"는 Valuables 아래 개체를 따라가는 추론으로 처리됨.

![분류 계층과 개체](images/knowledge_graph_1.jpg)

**② 상태 스냅샷 — 시연 시작 시점(17.2)** — `located_in` 기록과, 1막 1-7에서 관측 후 수정되는 차키 위치(주황 점선).

![상태 스냅샷](images/knowledge_graph_2.jpg)

**③ 스킬 인과 체인 — 2막 "립밤은 아래 서랍에 넣어 둬"** — 각 스킬의 결과가 다음 스킬의 조건을 채우는 관계. 서랍을 먼저 여는 순서가 조건에서 도출됨(7.7).

![스킬 인과 체인](images/knowledge_graph_3.jpg)

> **최종본 작성 시 확인**: Day 2 파지 테스트로 확정된 물품, 실제 서랍·트레이 구성, 17.2 초기 배치, 2막 명령 문장, 그림 속 용어(`located_in`, `open`, `gripper`)와 7.5 온톨로지 키 일치.
