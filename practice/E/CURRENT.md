# CURRENT — E 고희태

- **담당**: 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 (조장) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-03

## 지금 상태
- GitHub Actions PR 리뷰 자동화 추가: Markdown 전용은 Luna/low, 일반 코드는 Sol/medium, `review:deep` 및 안전·복구 경로는 Sol/high로 라우팅한다. 리뷰는 Codex `:read-only` 프로필로 diff와 주변 코드를 읽고 코멘트를 남기며 프로젝트 코드는 실행하지 않는다. [문서]

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| AI PR 리뷰 모델 라우팅 | Markdown: `gpt-6-luna`/low, 일반 코드: `gpt-6.1-sol`/medium, deep·안전 복구: `gpt-6.1-sol`/high | [문서] |

## 막힌 점 · 필요한 도움
-

## 다음 할 일
- [ ] GitHub Actions secrets에 `OPENAI_API_KEY` 등록 및 `review:deep` 라벨 생성
- [ ] 실제 PR에서 workflow 권한, 모델 라우팅, 코멘트 게시 확인

## 철회한 결론
-
