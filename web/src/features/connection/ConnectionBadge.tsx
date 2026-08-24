import { CircleAlert, CircleCheck, LoaderCircle, Radio } from "lucide-react";

export type ConnectionStatus = "checking" | "connected" | "disconnected";

interface ConnectionBadgeProps {
  status: ConnectionStatus;
  onReconnect: () => void;
}

export function ConnectionBadge({ status, onReconnect }: ConnectionBadgeProps) {
  const copy = {
    checking: "연결 확인 중",
    connected: "로컬 워커 연결됨",
    disconnected: "연결 끊김",
  }[status];
  const Icon = status === "connected" ? CircleCheck : status === "disconnected" ? CircleAlert : LoaderCircle;
  return (
    <div className={`connection-badge connection-${status}`} role="status" aria-live="polite">
      <Icon size={15} aria-hidden="true" className={status === "checking" ? "spin" : undefined} />
      <span>{copy}</span>
      {status === "disconnected" && (
        <button type="button" className="quiet-button" onClick={onReconnect}>
          <Radio size={13} aria-hidden="true" /> 다시 연결
        </button>
      )}
    </div>
  );
}
