import React, { useState, useEffect, useContext, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { AuthContext } from "../context/AuthContext";
import Navbar from "../components/Navbar";
import api from "../services/api";

// Module-level cache — survives React navigation (component unmount/remount)
let _poolCache = null;
let _poolCacheTime = 0;
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

const CATEGORIES = [
  { name: "Phones & Tablets",    icon: "📱" },
  { name: "Computers & Laptops", icon: "💻" },
  { name: "Audio & Sound",       icon: "🎧" },
  { name: "Gaming",              icon: "🎮" },
  { name: "Smart Home",          icon: "🏠" },
  { name: "Cameras & Drones",    icon: "📷" },
];

const fallback = e => { e.target.onerror = null; e.target.src = "/logo.png"; e.target.style.objectFit = "contain"; e.target.style.padding = "28px"; e.target.style.background = "#f3f4f6"; e.target.style.width = "100%"; e.target.style.height = "100%"; };

const ItemCard = ({ item, onClick }) => (
  <div className="item-card" onClick={onClick}>
    <img
      src={item.thumbnail || "/logo.png"}
      alt={item.title}
      className="item-image"
      onError={fallback}
      style={!item.thumbnail ? { objectFit: "contain", padding: "28px", background: "#f3f4f6" } : {}}
    />
    <div className="item-info">
      <h4 className="item-title">{item.title}</h4>
      <p className="item-price">${item.price?.toFixed(2)}</p>
      <p className="item-location">{item.city}, {item.state}</p>
      <span className="item-category">{item.category}</span>
    </div>
  </div>
);

const ScrollRow = ({ items, onItemClick }) => (
  <div className="scroll-row">
    {items.map(item => (
      <div key={item.item_id} className="scroll-card" onClick={() => onItemClick(item.item_id)}>
        <img
          src={item.thumbnail || "/logo.png"}
          alt={item.title}
          className="scroll-img"
          onError={fallback}
          style={!item.thumbnail ? { objectFit: "contain", padding: "20px", background: "#f3f4f6" } : {}}
        />
        <div className="scroll-info">
          <p className="scroll-title">{item.title}</p>
          <p className="scroll-price">${item.price?.toFixed(2)}</p>
          <span className="item-category">{item.category}</span>
        </div>
      </div>
    ))}
  </div>
);

const SkeletonRow = () => (
  <div className="scroll-row">
    {[...Array(5)].map((_, i) => (
      <div key={i} className="scroll-card skeleton-card">
        <div className="scroll-img skeleton-box" />
        <div className="scroll-info">
          <div className="skeleton-line" style={{ width: "80%" }} />
          <div className="skeleton-line" style={{ width: "40%", marginTop: 6 }} />
        </div>
      </div>
    ))}
  </div>
);

export default function Home() {
  const navigate  = useNavigate();
  const { token } = useContext(AuthContext);

  const cached = _poolCache && (Date.now() - _poolCacheTime < CACHE_TTL);
  const [pool,        setPool]        = useState(cached ? _poolCache : []);
  const [poolLoading, setPoolLoading] = useState(!cached);

  const [searchInput, setSearchInput] = useState("");
  const [search,      setSearch]      = useState("");
  const [category,    setCategory]    = useState("");
  const [results,     setResults]     = useState([]);
  const [total,       setTotal]       = useState(0);
  const [resLoading,  setResLoading]  = useState(false);
  const [error,       setError]       = useState("");

  const isFiltering = !!(search || category);

  // Load pool — skip if cache is still fresh
  useEffect(() => {
    if (cached) return;
    setPoolLoading(true);
    api.get("/marketplace/items?limit=120&skip=0")
      .then(r => {
        const items = r.data.items || [];
        _poolCache = items;
        _poolCacheTime = Date.now();
        setPool(items);
        setPoolLoading(false);
      })
      .catch(() => setPoolLoading(false));
  }, []);

  // Load filtered results
  useEffect(() => {
    if (!isFiltering || !token) { setResults([]); return; }
    setResLoading(true); setError("");
    const p = new URLSearchParams({ limit: 40, skip: 0 });
    if (search)   p.set("search",   search);
    if (category) p.set("category", category);
    api.get(`/marketplace/items?${p}`)
      .then(r => { setResults(r.data.items || []); setTotal(r.data.total); })
      .catch(() => setError("Failed to load listings."))
      .finally(() => setResLoading(false));
  }, [search, category, token]);

  const clearFilter = useCallback(() => {
    setSearch(""); setSearchInput(""); setCategory("");
  }, []);

  // Derive sections from pool
  const trending    = [...pool].sort((a, b) => b.views_count  - a.views_count ).slice(0, 10);
  const mostSaved   = [...pool].sort((a, b) => b.saves_count  - a.saves_count ).slice(0, 10);
  const newArrivals = [...pool].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 10);

  return (
    <div className="app-shell">
      <Navbar />

      {/* Search bar */}
      <div className="home-search-wrap">
        <form className="home-search-bar"
          onSubmit={e => { e.preventDefault(); setSearch(searchInput); setCategory(""); }}>
          <input
            placeholder="Search for anything…"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
          />
          <button type="submit">Search</button>
          {isFiltering && (
            <button type="button" className="btn-clear" onClick={clearFilter}>✕ Clear</button>
          )}
        </form>

        {/* Category pills */}
        <div className="cat-pills">
          {CATEGORIES.map(c => (
            <button
              key={c.name}
              className={`cat-pill ${category === c.name ? "active" : ""}`}
              onClick={() => { setCategory(category === c.name ? "" : c.name); setSearch(""); setSearchInput(""); }}
            >
              {c.icon} {c.name}
            </button>
          ))}
        </div>
      </div>

      {/* ── FILTER MODE ── */}
      {isFiltering && (
        <div className="results-wrap">
          <p className="results-label">
            {resLoading ? "Searching…" : `${total} result${total !== 1 ? "s" : ""}${category ? ` in ${category}` : ""}${search ? ` for "${search}"` : ""}`}
          </p>
          {error && <p className="status-text error">{error}</p>}
          <div className="items-grid">
            {results.map(item => (
              <ItemCard key={item.item_id} item={item} onClick={() => navigate(`/item/${item.item_id}`)} />
            ))}
          </div>
          {!resLoading && results.length === 0 && !error && (
            <p className="status-text" style={{ textAlign:"center", marginTop:48 }}>
              No listings found.{" "}
              <button className="link-btn" onClick={clearFilter}>Browse all</button>
            </p>
          )}
        </div>
      )}

      {/* ── HOME MODE ── */}
      {!isFiltering && (
        <div className="home-sections">

          {/* Trending Now */}
          <section className="rec-section">
            <div className="rec-header">
              <h2 className="rec-title">🔥 Trending Now</h2>
              <span className="rec-sub">Most viewed listings</span>
            </div>
            {poolLoading ? <SkeletonRow /> : trending.length > 0
              ? <ScrollRow items={trending} onItemClick={id => navigate(`/item/${id}`)} />
              : <p className="status-text">Loading products…</p>}
          </section>

          {/* Most Saved */}
          <section className="rec-section">
            <div className="rec-header">
              <h2 className="rec-title">❤️ Most Saved</h2>
              <span className="rec-sub">People are loving these</span>
            </div>
            {poolLoading ? <SkeletonRow /> : mostSaved.length > 0
              ? <ScrollRow items={mostSaved} onItemClick={id => navigate(`/item/${id}`)} />
              : <p className="status-text">Loading products…</p>}
          </section>

          {/* New Arrivals */}
          <section className="rec-section">
            <div className="rec-header">
              <h2 className="rec-title">✨ New Arrivals</h2>
              <span className="rec-sub">Just listed</span>
            </div>
            {poolLoading ? <SkeletonRow /> : newArrivals.length > 0
              ? <ScrollRow items={newArrivals} onItemClick={id => navigate(`/item/${id}`)} />
              : <p className="status-text">Loading products…</p>}
          </section>

          {/* Browse by Category */}
          <section className="rec-section">
            <div className="rec-header">
              <h2 className="rec-title">Browse by Category</h2>
            </div>
            <div className="cat-browse-grid">
              {CATEGORIES.map(c => {
                const count = pool.filter(i => i.category === c.name).length;
                return (
                  <div key={c.name} className="cat-browse-card" onClick={() => setCategory(c.name)}>
                    <span className="cat-browse-icon">{c.icon}</span>
                    <span className="cat-browse-name">{c.name}</span>
                    <span className="cat-browse-count">
                      {poolLoading ? "—" : `${count}+ listings`}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

        </div>
      )}
    </div>
  );
}
