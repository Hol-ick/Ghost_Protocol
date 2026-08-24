import { ArrowDown, Orbit } from "lucide-react";

export function StudioEmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-orbit"><Orbit size={26} aria-hidden="true" /></div>
      <p className="empty-kicker">NO ACTIVE RUN</p>
      <h3>첫 번째 신호를 관측하세요</h3>
      <p>왼쪽 Run Control에서 모드를 선택하고 시작하면<br />로컬 워커의 heartbeat와 이벤트가 이곳에 나타납니다.</p>
      <span className="empty-arrow"><ArrowDown size={15} aria-hidden="true" /> Run Control에서 시작</span>
    </div>
  );
}
