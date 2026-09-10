import React, { useState, useEffect, useContext } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { AuthContext } from "../context/AuthContext";
import Navbar from "../components/Navbar";
import api from "../services/api";

const ItemDetail = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useContext(AuthContext);

  const [item,        setItem]        = useState(null);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState("");
  const [buyerConvos, setBuyerConvos] = useState([]);
  const [similar,     setSimilar]     = useState([]);
  const [saved,       setSaved]       = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);

  useEffect(() => {
    api.get(`/marketplace/items/${id}`)
      .then(r => setItem(r.data))
      .catch(() => setError("Item not found."))
      .finally(() => setLoading(false));

    api.get(`/recommendations/${id}?limit=6`)
      .then(r => setSimilar(r.data.recommendations || []))
      .catch(() => {});

    api.get(`/marketplace/items/${id}/saved`)
      .then(r => setSaved(r.data.saved))
      .catch(() => {});
  }, [id]);

  const isMine = item?.seller_id === user?.user_id;

  // Seller: load buyer conversations for this item
  useEffect(() => {
    if (!isMine || !item) return;
    api.get("/messages/inbox?limit=100")
      .then(r => {
        const msgs = r.data.messages || [];
        const forItem = msgs.filter(m => m.item_id === item.item_id);
        const latest = new Map();
        forItem.forEach(m => {
          const existing = latest.get(m.sender_id);
          if (!existing || new Date(m.sent_at) > new Date(existing.sent_at)) {
            latest.set(m.sender_id, m);
          }
        });
        setBuyerConvos(Array.from(latest.values())
          .sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at)));
      })
      .catch(() => {});
  }, [isMine, item]);

  const toggleSave = async () => {
    setSaveLoading(true);
    try {
      if (saved) {
        const r = await api.delete(`/marketplace/items/${id}/save`);
        setSaved(false);
        if (r.data.saves_count !== null)
          setItem(prev => ({ ...prev, saves_count: r.data.saves_count }));
      } else {
        const r = await api.post(`/marketplace/items/${id}/save`);
        setSaved(true);
        if (r.data.saves_count !== null)
          setItem(prev => ({ ...prev, saves_count: r.data.saves_count }));
      }
    } catch {
      // silent — user sees no state change
    } finally {
      setSaveLoading(false);
    }
  };

  if (loading) return <div className="center-text">Loading…</div>;
  if (error)   return <div className="center-text error">{error}</div>;
  if (!item)   return null;

  return (
    <div className="app-shell">
      <Navbar showBack />

      <div className="detail-body">
        {/* Images */}
        <div className="detail-images">
          {(item.images?.length > 0 ? item.images : [null]).map((url, i) => (
            <img
              key={i}
              src={url || "/logo.png"}
              alt={item.title}
              className="detail-img"
              onError={e => { e.target.onerror = null; e.target.src = "/logo.png"; e.target.style.objectFit = "contain"; e.target.style.padding = "32px"; e.target.style.background = "#f8f9ff"; }}
            />
          ))}
        </div>

        {/* Info panel */}
        <div className="detail-panel">
          <h1 className="detail-title">{item.title}</h1>
          <p className="detail-price">${item.price?.toFixed(2)}</p>

          <div className="detail-badges">
            <span className="badge">{item.category}</span>
            <span className="badge">{item.condition}</span>
          </div>

          <p className="detail-location">📍 {item.city}, {item.state}</p>

          <div className="detail-stats">
            <span>👁 {item.views_count} views</span>
            <span>❤️ {item.saves_count} saves</span>
            {!isMine && (
              <button
                className={`btn-save ${saved ? "saved" : ""}`}
                onClick={toggleSave}
                disabled={saveLoading}
                title={saved ? "Remove from wishlist" : "Save to wishlist"}
              >
                {saved ? "♥ Saved" : "♡ Save"}
              </button>
            )}
          </div>

          <hr className="divider" />
          <h3>Description</h3>
          <p className="detail-desc">{item.description}</p>
          <hr className="divider" />

          {isMine ? (
            <div>
              <div className="own-listing-note">This is your listing</div>
              {buyerConvos.length > 0 ? (
                <div className="buyer-convos">
                  <h4 className="buyer-convos-title">
                    Messages from buyers ({buyerConvos.length})
                  </h4>
                  {buyerConvos.map(m => (
                    <div
                      key={m.sender_id}
                      className="buyer-row"
                      onClick={() => navigate(`/thread/${item.item_id}/${m.sender_id}`)}
                    >
                      <div className="buyer-avatar">
                        {m.sender_id.slice(-2).toUpperCase()}
                      </div>
                      <div className="buyer-info">
                        <span className="buyer-name">{m.sender_id}</span>
                        <p className="buyer-preview">
                          {m.text?.slice(0, 60)}{m.text?.length > 60 ? "…" : ""}
                        </p>
                      </div>
                      <button className="btn-reply">Reply →</button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="status-text" style={{ marginTop: 12 }}>
                  No messages yet for this listing.
                </p>
              )}
            </div>
          ) : (
            <button
              className="btn-primary"
              onClick={() => navigate(`/thread/${item.item_id}/${item.seller_id}`)}
            >
              💬 Message Seller
            </button>
          )}
        </div>
      </div>

      {/* ── Similar Listings ── */}
      {similar.length > 0 && (
        <div className="similar-section">
          <h3 className="similar-title">Similar Listings</h3>
          <div className="similar-grid">
            {similar.map(rec => (
              <div
                key={rec.item_id}
                className="item-card"
                onClick={() => navigate(`/item/${rec.item_id}`)}
              >
                <img
                  src={rec.thumbnail || "/logo.png"}
                  alt={rec.title}
                  className="item-image"
                  onError={e => { e.target.onerror = null; e.target.src = "/logo.png"; e.target.style.objectFit = "contain"; e.target.style.padding = "16px"; e.target.style.background = "#f8f9ff"; }}
                />
                <div className="item-info">
                  <h4 className="item-title">{rec.title}</h4>
                  <p className="item-price">${rec.price?.toFixed(2)}</p>
                  <p className="item-location">{rec.city}, {rec.state}</p>
                  <span className="item-category">{rec.category}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ItemDetail;
