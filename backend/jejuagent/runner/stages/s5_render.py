"""⑤ 렌더 (티켓 08).

입력: state.plan(output_format), state.artifacts, state.selection, state.tasks, state.unanswered, state.load_failures
출력: state.html, 그리고 최종 상태. 분석한 것이 없고(중간산출물·선택·미답변 없음) 상한도 아니면 통과(HTML 없음).
종료 상태: 상한·로드 실패·unanswered·성공하지 못한 작업이 있으면 partial, 아니면 answered.
상한에 걸리면 ctx.llm이 막혀 있어 render 패키지가 LLM 없이 결정적 폴백으로 렌더한다.
"""
from ...render import build_html


def run(state, ctx):
    if not (state.artifacts or state.unanswered or state.limit_hit or state.load_failures):
        return state
    state.html, info = build_html(state, ctx)
    ctx.trace.add("decision", stage="s5_render", format=(state.plan or {}).get("output_format"), fallback=info["fallback"],
                  fallback_reason=info["reason"], removed_sentences=info["removed"])
    incomplete = (state.limit_hit or state.load_failures or state.unanswered
                  or any(t.get("status") != "ok" for t in state.tasks))
    state.finish("partial" if incomplete else "answered",
                 message="상한에 걸려 그때까지의 결과로 렌더했습니다." if state.limit_hit else state.message)
    return state
