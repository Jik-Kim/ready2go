# sim — Isaac Sim 트윈 (담당 A 김병직, Phase 2~)

> 문서: [`docs/twin.md`](../docs/twin.md)

- Isaac Sim 5.1.0 **네이티브 실행**(컨테이너 아님). 호스트 ROS 2 Jazzy + CycloneDDS를 source한 뒤 실행.
- 팀 로직은 여기 두지 않음: 씬 로드, ROS 2 Bridge, 조인트 미러링 스크립트만.
- USD는 Git LFS(`.gitattributes`)로 관리하고 **A만 편집**. 기존 자산 출처: `~/isaac_legacy/M0609_jik` (M0609 + RG2 + 손목 카메라).
- Phase 1에는 필수 아님(씬 구성은 병행 가능).
