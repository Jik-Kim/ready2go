# ready2go

음성 명령으로 실물 **Doosan M0609 + OnRobot RG2**가 서랍 속 물건을 찾아 꺼내고 원상 복구하는 시스템.
로봇의 동작·상태를 **JSON 온톨로지**로 정의하고, 명령에 맞춰 조합하며, 모든 동작의 성공 여부를 기록한다.

- 문서: [`docs/README.md`](docs/README.md) (인덱스부터) · 요구사항 기준 원본: [`docs/requirements.md`](docs/requirements.md) · 단계 요약: [`docs/phases.md`](docs/phases.md)
- 스택: ROS 2 Jazzy · CycloneDDS(`ROS_DOMAIN_ID=70`) · Docker Compose · Python · MongoDB · Isaac Sim 5.1.0(트윈, 네이티브)

## 실행 (장비별 명령 1개)
`.env.example`을 `.env`로 복사해 장비별 값을 채운 뒤:

```bash
docker compose --profile real up   # PC2: 실물 로봇 옆 (BACKEND=real)
docker compose --profile sim up    # PC1: Isaac Sim 사전 검증 (Phase 2~)
docker compose --profile dev up    # 개발: 로봇·GPU 없이 (BACKEND=mock)
```

호스트 준비(sysctl 버퍼, xhost, PulseAudio 등): [`docs/docker.md`](docs/docker.md)

## 저장소 구조
| 경로 | 내용 |
| :--- | :--- |
| `docs/` | 요구사항 기준 원본과 주제별 기술 문서. `archive/`는 과거 스냅샷 |
| `contracts/` | JSON Schema 계약 + `examples/` |
| `knowledge/` | 로봇 온톨로지(`robot_ontology.jsonld`), 상태 스냅샷 |
| `tasks/` | 태스크(복합 스킬) JSON |
| `config/` | 장비·실측값: DDS, 기준 포즈, 서랍 좌표계, 캘리브레이션 |
| `ros2_ws/src/` | ROS 2 패키지 `ready2go_*` |
| `docker/` | 서비스별 Dockerfile |
| `sim/` | Isaac Sim 스크립트 (USD는 Git LFS) |
| `tools/` | 검증·측정 스크립트 |
| `practice/` | 담당별 현재 상태(`CURRENT.md`) |

## 팀
| 코드 | 이름 | 담당 |
| :--- | :--- | :--- |
| A | 김병직 | 비전 · Isaac Sim 트윈 |
| B | 서동권 | 실물 로봇 모션 |
| C | 이영훈 | Runner · 플래너 · 로그 · 기술 통합 |
| D | 김민준 | 기록 · 문서 · 평가 자료 |
| E | 고희태 (조장) | 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 |
