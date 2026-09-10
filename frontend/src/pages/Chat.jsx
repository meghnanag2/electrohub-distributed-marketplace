import React, { useState, useEffect, useRef, useContext } from "react";
import { AuthContext } from "../context/AuthContext";
import { API_BASE_URL } from "../services/api";

/**
 * Real-time buyer-seller chat for a specific item.
 *
 * Usage: <Chat itemId={42} sellerId="user_000003" />
 *
 * WebSocket path: ws://localhost/messages/ws/{itemId}/{sellerId}?token={jwt}
 * On connect: server sends { type: "history", messages: [...] }
 * On message: server broadcasts { type: "message", sender_id, text, sent_at }
 */
const Chat = ({ itemId, sellerId, sellerName }) => {
  const { token, user } = useContext(AuthContext);
  const [messages, setMessages]   = useState([]);
  const [input, setInput]         = useState("");
  const [status, setStatus]       = useState("connecting");
  const wsRef   = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (!token || !itemId || !sellerId) return;

    // API_BASE_URL is "" for same-origin deployments (local dev, or Nginx
    // serving both frontend+backend) — fall back to the page's own host.
    // When the frontend is deployed separately (e.g. Vercel), API_BASE_URL
    // is an absolute http(s) URL pointing at the backend — reuse its host
    // and derive ws/wss from its protocol instead of the page's protocol.
    let wsUrl;
    if (API_BASE_URL) {
      const backend = new URL(API_BASE_URL);
      const wsProtocol = backend.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${wsProtocol}//${backend.host}/messages/ws/${itemId}/${sellerId}?token=${token}`;
    } else {
      const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${wsProtocol}//${window.location.host}/messages/ws/${itemId}/${sellerId}?token=${token}`;
    }
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen  = () => setStatus("connected");
    ws.onclose = () => setStatus("disconnected");
    ws.onerror = () => setStatus("error");

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === "history") {
        setMessages(data.messages);
      } else if (data.type === "message") {
        setMessages((prev) => [...prev, data]);
      }
    };

    return () => ws.close();
  }, [token, itemId, sellerId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = (e) => {
    e.preventDefault();
    if (!input.trim() || wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ text: input.trim() }));
    setInput("");
  };

  const statusColor = {
    connecting: "#f59e0b",
    connected: "#10b981",
    disconnected: "#6b7280",
    error: "#ef4444",
  }[status];

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span>Chat with {sellerName || sellerId}</span>
        <span style={{ ...styles.dot, background: statusColor }} title={status} />
      </div>

      <div style={styles.messageList}>
        {messages.map((m, i) => {
          const mine = m.sender_id === user?.user_id;
          return (
            <div key={m.message_id || i} style={{
              ...styles.bubble,
              alignSelf: mine ? "flex-end" : "flex-start",
              background: mine ? "#6366f1" : "#f3f4f6",
              color: mine ? "#fff" : "#111",
            }}>
              <p style={styles.bubbleText}>{m.text}</p>
              <span style={styles.bubbleTime}>
                {new Date(m.sent_at).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})}
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={send} style={styles.form}>
        <input
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={status === "connected" ? "Type a message…" : "Connecting…"}
          disabled={status !== "connected"}
        />
        <button style={styles.btn} type="submit" disabled={status !== "connected"}>
          Send
        </button>
      </form>
    </div>
  );
};

const styles = {
  container:   { display:"flex", flexDirection:"column", height:420, border:"1px solid #e5e7eb", borderRadius:8, overflow:"hidden", fontFamily:"sans-serif" },
  header:      { display:"flex", justifyContent:"space-between", alignItems:"center", padding:"10px 14px", background:"#1e1b4b", color:"#fff", fontSize:14, fontWeight:600 },
  dot:         { width:10, height:10, borderRadius:"50%", display:"inline-block" },
  messageList: { flex:1, overflowY:"auto", padding:12, display:"flex", flexDirection:"column", gap:8, background:"#fff" },
  bubble:      { maxWidth:"70%", padding:"8px 12px", borderRadius:14, display:"flex", flexDirection:"column", gap:2 },
  bubbleText:  { margin:0, fontSize:14, lineHeight:1.4 },
  bubbleTime:  { fontSize:10, opacity:0.6, alignSelf:"flex-end" },
  form:        { display:"flex", borderTop:"1px solid #e5e7eb", padding:8, gap:8, background:"#f9fafb" },
  input:       { flex:1, padding:"8px 12px", borderRadius:6, border:"1px solid #d1d5db", fontSize:14, outline:"none" },
  btn:         { padding:"8px 16px", background:"#6366f1", color:"#fff", border:"none", borderRadius:6, cursor:"pointer", fontSize:14, fontWeight:600 },
};

export default Chat;
