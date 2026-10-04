import { dateTime } from "../services/format";
import type { Notification } from "../types/api";

export function NotificationsList({ items }: { items: Notification[] }) {
  return (
    <section className="card">
      <h2>Alertes</h2>
      {items.length === 0 ? (
        <p className="muted">Aucune alerte.</p>
      ) : (
        <ul className="list">
          {items.map((n) => (
            <li key={n.id}>
              <span className="small muted">{dateTime(n.timestamp)}</span> <code>{n.event}</code>
              <div className="pre">{n.message}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
