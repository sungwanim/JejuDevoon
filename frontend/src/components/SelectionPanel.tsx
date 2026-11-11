import type { TraceEvent } from "../api";

type Sel = { dataset_id: string; reason?: string; role?: string };
type Exc = { dataset_id: string; reason_code: string; note?: string };
type Sub = { question: string; status: string; why?: string };

const CODE: Record<string, string> = {
  irrelevant: "관련 없음",
  granularity_mismatch: "공간 단위 불일치",
  out_of_region: "지역 밖",
  out_of_period: "기간 밖",
  missing_columns: "필요 컬럼 없음",
};

export default function SelectionPanel({ events }: { events: TraceEvent[] }) {
  const ev = events.find((e) => e.type === "decision" && e.stage === "s2_select" && e.selected);
  if (!ev) return null;
  const sel = ev.selected as Sel[];
  const exc = ev.excluded as Exc[];
  const subs = (ev.sub_questions as Sub[]) ?? [];
  return (
    <section className="panel selection">
      <h3>데이터 선택</h3>
      <h4>사용한 데이터 ({sel.length})</h4>
      <ul>
        {sel.map((s) => (
          <li key={s.dataset_id}>
            <b>{s.dataset_id}</b>
            {s.role === "auxiliary" && " (보조)"} <span className="muted">{s.reason}</span>
          </li>
        ))}
        {!sel.length && <li className="muted">없음</li>}
      </ul>
      <h4>제외한 데이터 ({exc.length})</h4>
      <ul>
        {exc.map((x) => (
          <li key={x.dataset_id}>
            <b>{x.dataset_id}</b> [{CODE[x.reason_code] ?? x.reason_code}] <span className="muted">{x.note}</span>
          </li>
        ))}
      </ul>
      <h4>하위 질문별 상태</h4>
      <ul>
        {subs.map((q, i) => (
          <li key={i}>
            {q.status === "unanswered" ? "답할 수 없음" : "답변 예정"}: {q.question}
            {q.why && <span className="muted"> ({q.why})</span>}
          </li>
        ))}
        {((ev.unanswered as { what: string; why: string }[]) ?? [])
          .filter((u) => !subs.some((q) => q.question === u.what))
          .map((u, i) => (
            <li key={"u" + i}>
              답할 수 없음: {u.what} <span className="muted">({u.why})</span>
            </li>
          ))}
      </ul>
    </section>
  );
}
