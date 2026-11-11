import type { RunResult } from "../api";

const save = (html: string, id: string) => {
  const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `jeju-result-${id}.html` });
  a.click();
  URL.revokeObjectURL(url);
};

export default function ResultView({ r }: { r: RunResult | null }) {
  if (!r || r.running) return null;
  return (
    <section className="panel result">
      {r.message && <p className="message">{r.message}</p>}
      {r.needed_data.length > 0 && (
        <ul>
          {r.needed_data.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
      {r.unanswered.length > 0 && (
        <ul>
          {r.unanswered.map((u, i) => (
            <li key={i}>
              {u.what}: {u.why}
            </li>
          ))}
        </ul>
      )}
      {r.html ? (
        <>
          <button onClick={() => save(r.html!, r.run_id)}>결과를 HTML 파일로 저장</button>
          <iframe title="결과" srcDoc={r.html} sandbox="allow-scripts" className="result-frame" />
        </>
      ) : (
        r.status === "answered" && <p className="muted">(분석 단계 미구현: HTML 결과가 아직 없습니다)</p>
      )}
    </section>
  );
}
