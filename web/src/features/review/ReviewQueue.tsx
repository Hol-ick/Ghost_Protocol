import { ClipboardCheck } from "lucide-react";
import type { RunEvent } from "../../types";

export function ReviewQueue({ events }: { events: RunEvent[] }) {
  const reviewable = events.filter((event) => event.kind === "preview" || event.kind === "insight").slice(-3).reverse();
  return (
    <section className="subpanel review-queue" aria-labelledby="review-title">
      <div className="subpanel-heading"><span className="subpanel-icon green"><ClipboardCheck size={14} /></span><div><h3 id="review-title">Review queue</h3><p>사람의 판단이 필요한 항목</p></div><span className="queue-count">{reviewable.length}</span></div>
      {reviewable.length === 0 ? <p className="review-empty">새로운 검토 항목이 없습니다.</p> : <ul>{reviewable.map((event) => <li key={`${event.runId}-${event.sequence}`}><span className="review-marker" /><span>{event.message || "검토용 신호"}</span><small>seq {event.sequence}</small></li>)}</ul>}
    </section>
  );
}
