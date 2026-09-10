import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../services/api";

const Inbox = () => {
  const navigate = useNavigate();
  const [convos, setConvos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/messages/inbox?limit=100")
      .then(r => {
        const msgs = r.data.messages || [];

        // Group by (item_id, sender_id) — keep latest message per thread
        const latest = new Map();
        const unreadCount = new Map();

        msgs.forEach(m => {
          const key = `${m.item_id}::${m.sender_id}`;
          const existing = latest.get(key);
          if (!existing || new Date(m.sent_at) > new Date(existing.sent_at)) {
            latest.set(key, m);
          }
          if (!m.is_read) {
            unreadCount.set(key, (unreadCount.get(key) || 0) + 1);
          }
        });

        const list = Array.from(latest.values())
          .map(m => ({ ...m, unread: unreadCount.get(`${m.item_id}::${m.sender_id}`) || 0 }))
          .sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at));

        setConvos(list);
      })
      .catch(() => setError("Could not load inbox."))
      .finally(() => setLoading(false));
  }, []);

  const initials = (id) => id?.slice(-2).toUpperCase() || "??";

  return (
    <div className="app-shell">
      <Navbar />
      <div className="inbox-body">
        <h2>Inbox {convos.length > 0 && <span className="inbox-count">{convos.length}</span>}</h2>

        {loading && <p className="status-text">Loading…</p>}
        {error   && <p className="status-text error">{error}</p>}
        {!loading && convos.length === 0 && !error && (
          <p className="status-text">No messages yet.</p>
        )}

        <ul className="conv-list">
          {convos.map(m => (
            <li
              key={`${m.item_id}-${m.sender_id}`}
              className={`conv-row ${m.unread > 0 ? "unread" : ""}`}
              onClick={() => navigate(`/thread/${m.item_id}/${m.sender_id}`)}
            >
              <div className="conv-avatar">{initials(m.sender_id)}</div>
              <div className="conv-info">
                <div className="conv-top">
                  <span className="conv-name">{m.sender_id}</span>
                  <span className="conv-time">
                    {new Date(m.sent_at).toLocaleDateString([], { month: "short", day: "numeric" })}
                  </span>
                </div>
                <p className="conv-preview">
                  {m.text?.slice(0, 80)}{m.text?.length > 80 ? "…" : ""}
                </p>
                <span className="conv-item-tag">Item #{m.item_id}</span>
              </div>
              {m.unread > 0 && <span className="conv-badge">{m.unread}</span>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default Inbox;
