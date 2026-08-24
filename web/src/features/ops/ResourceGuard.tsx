import { Database, ShieldCheck } from "lucide-react";

export function ResourceGuard({ connected }: { connected: boolean }) {
  return (
    <section className="subpanel resource-guard" aria-labelledby="resource-title">
      <div className="subpanel-heading"><span className="subpanel-icon gray"><ShieldCheck size={14} /></span><div><h3 id="resource-title">Resource guard</h3><p>로컬 리소스 상태</p></div><span className="guard-status">SAFE</span></div>
      <div className="resource-row"><Database size={14} aria-hidden="true" /><span>SQLite ledger</span><strong>{connected ? "READY" : "OFFLINE"}</strong></div>
      <div className="resource-row"><span className="resource-bars"><i /><i /><i /></span><span>Worker queue</span><strong>{connected ? "LOCAL" : "PAUSED"}</strong></div>
      <p className="resource-note">브라우저는 로컬 제어 API만 호출합니다. 비밀 키와 세션은 이 화면에 노출되지 않습니다.</p>
    </section>
  );
}
