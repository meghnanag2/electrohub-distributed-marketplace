import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../services/api";

export default function Saved() {
  const navigate = useNavigate();
  const [items,   setItems]   = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/marketplace/users/me/saved")
      .then(r => setItems(r.data.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const unsave = async (itemId) => {
    await api.delete(`/marketplace/items/${itemId}/save`).catch(() => {});
    setItems(prev => prev.filter(i => i.item_id !== itemId));
  };

  return (
    <div className="app-shell">
      <Navbar showBack />

      <div className="saved-wrap">
        <h2 className="saved-title">♥ Saved Items</h2>

        {loading && <p className="status-text">Loading…</p>}

        {!loading && items.length === 0 && (
          <p className="status-text" style={{ textAlign: "center", marginTop: 48 }}>
            Nothing saved yet.{" "}
            <button className="link-btn" onClick={() => navigate("/")}>Browse listings</button>
          </p>
        )}

        <div className="items-grid">
          {items.map(item => (
            <div key={item.item_id} className="item-card" style={{ position: "relative" }}>
              <button
                className="btn-unsave"
                onClick={(e) => { e.stopPropagation(); unsave(item.item_id); }}
                title="Remove from saved"
              >✕</button>
              <div onClick={() => navigate(`/item/${item.item_id}`)}>
                <img
                  src={item.thumbnail || "/logo.png"}
                  alt={item.title}
                  className="item-image"
                  onError={e => { e.target.onerror = null; e.target.src = "/logo.png"; e.target.style.objectFit = "contain"; e.target.style.padding = "16px"; e.target.style.background = "#f8f9ff"; }}
                />
                <div className="item-info">
                  <h4 className="item-title">{item.title}</h4>
                  <p className="item-price">${item.price?.toFixed(2)}</p>
                  <p className="item-location">{item.city}, {item.state}</p>
                  <span className="item-category">{item.category}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
