import { useState } from "react";

export default function ChatInput({ disabled, onSend }: { disabled: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const submit = () => {
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText("");
  };
  return (
    <div className="chat-input">
      <textarea
        value={text}
        placeholder="예: 제주공항 소음측정소 중 소음도가 가장 높은 곳은?"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <button onClick={submit} disabled={disabled || !text.trim()}>
        {disabled ? "분석 중…" : "보내기"}
      </button>
    </div>
  );
}
