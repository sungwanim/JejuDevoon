import type { RunStatus } from "../api";

const STAGES = ["s1_parse", "s2_select", "s3_load", "s4_analyze", "s5_render"];
const LABELS: Record<string, string> = {
  s1_parse: "① 요청 규격화",
  s2_select: "② 데이터 선택",
  s3_load: "③ 로드·Profile",
  s4_analyze: "④ 분석",
  s5_render: "⑤ 렌더",
};
const STATUS_LABEL: Record<string, string> = {
  answered: "답변 완료",
  partial: "일부 답변",
  clarify: "되묻기",
  infeasible: "불가",
  failed: "실패",
};

export default function StageStatus({ s }: { s: RunStatus | null }) {
  if (!s) return null;
  const cur = STAGES.indexOf(s.stage ?? "");
  return (
    <div className="stages">
      {STAGES.map((st, i) => (
        <span key={st} className={"stage " + (s.running && i === cur ? "active" : cur >= 0 && i < cur ? "done" : "")}>
          {LABELS[st]}
        </span>
      ))}
      {s.status && <span className={"badge " + s.status}>{STATUS_LABEL[s.status] ?? s.status}</span>}
    </div>
  );
}
