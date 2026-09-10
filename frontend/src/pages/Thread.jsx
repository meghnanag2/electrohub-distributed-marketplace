import React, { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import Navbar from "../components/Navbar";
import Chat from "./Chat";
import api from "../services/api";

const Thread = () => {
  const { itemId, otherUserId } = useParams();
  const [item, setItem] = useState(null);

  useEffect(() => {
    api.get(`/marketplace/items/${itemId}`)
      .then(r => setItem(r.data))
      .catch(() => {});
  }, [itemId]);

  return (
    <div className="app-shell">
      <Navbar showBack />
      <div className="thread-body">
        <div className="thread-header">
          <div>
            <h2 className="thread-title">{item ? item.title : `Item #${itemId}`}</h2>
            <p className="thread-subtitle">Chat with {otherUserId}</p>
          </div>
          {item && <span className="thread-price">${item.price?.toFixed(2)}</span>}
        </div>
        <div className="thread-chat">
          <Chat
            itemId={Number(itemId)}
            sellerId={otherUserId}
            sellerName={otherUserId}
          />
        </div>
      </div>
    </div>
  );
};

export default Thread;
