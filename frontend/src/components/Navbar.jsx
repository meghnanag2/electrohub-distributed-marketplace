import React, { useState, useEffect, useContext } from "react";
import { useNavigate } from "react-router-dom";
import { AuthContext } from "../context/AuthContext";
import api from "../services/api";

const Navbar = ({ showBack = false }) => {
  const navigate = useNavigate();
  const { user, logout } = useContext(AuthContext);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!user) return;
    const fetchUnread = () => {
      api.get("/messages/unread-count")
        .then(r => setUnread(r.data.unread || 0))
        .catch(() => {});
    };
    fetchUnread();
    const interval = setInterval(fetchUnread, 30000);
    return () => clearInterval(interval);
  }, [user]);

  return (
    <nav className="navbar">
      <img src="/logo.png" alt="ElectroHub" className="brand-logo" onClick={() => navigate("/")} />
      <div className="nav-actions">
        {showBack && (
          <button className="btn-ghost btn-signout" onClick={() => navigate(-1)}>← Back</button>
        )}
        <span className="nav-user">Hi, {user?.name || "User"}</span>
        <button className="btn-ghost notif-bell" onClick={() => navigate("/inbox")}>
          🔔 Inbox
          {unread > 0 && (
            <span className="notif-badge">{unread > 99 ? "99+" : unread}</span>
          )}
        </button>
        <button className="btn-ghost btn-saved" onClick={() => navigate("/saved")}>♥ Saved</button>
        <button className="btn-ghost btn-signout" onClick={logout}>Sign out</button>
      </div>
    </nav>
  );
};

export default Navbar;
