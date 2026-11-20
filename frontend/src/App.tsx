import { useRef, useState } from "react";
import { getResult, getStatus, startRun, type RunResult, type RunStatus } from "./api";
import JejuMap, { type Click } from "./components/JejuMap";
import ChatInput from "./components/ChatInput";
import ResultView from "./components/ResultView";
import StageStatus from "./components/StageStatus";
import SelectionPanel from "./components/SelectionPanel";
import ThoughtStream from "./components/ThoughtStream";
import TracePanel from "./components/TracePanel";

type Msg = { role: "user" | "agent"; text: string };

export default function App() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [click, setClick] = useState<Click | null>(null);
  const conv = useRef(crypto.randomUUID()); // 되묻기 이어쓰기용 대화 id

  const send = async (text: string) => {
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    setResult(null);
    try {
      const { run_id } = await startRun(text, click?.lat, click?.lon, conv.current);
      let s = await getStatus(run_id);
      setStatus(s);
      while (s.running) {
        await new Promise((r) => setTimeout(r, 400));
        s = await getStatus(run_id);
        setStatus(s);
      }
      const res = await getResult(run_id);
      setResult(res);
      setMsgs((m) => [...m, { role: "agent", text: res.message || res.reason || res.status || "" }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "agent", text: `오류: ${e instanceof Error ? e.message : e}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main>
      <h1>제주 공공데이터 분석 Agent</h1>
      <div className="log">
        {msgs.map((m, i) => (
          <div key={i} className={"msg " + m.role}>
            {m.text}
          </div>
        ))}
      </div>
      <JejuMap value={click} onPick={setClick} />
      <StageStatus s={status} />
      <ThoughtStream thoughts={status?.thoughts ?? []} running={busy} />
      {status?.status === "clarify" && !busy && (
        <div className="muted">되묻기에 답하면 이전 요청과 이어서 분석합니다. 위치가 필요하면 지도를 클릭한 뒤 보내세요.</div>
      )}
      <ChatInput disabled={busy} onSend={send} />
      <ResultView r={result} />
      <SelectionPanel events={result?.events ?? []} />
      <TracePanel events={result?.events ?? []} />
    </main>
  );
}
