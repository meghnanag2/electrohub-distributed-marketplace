import React, { useContext } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, AuthContext } from "./context/AuthContext";
import Login      from "./pages/Login";
import Home       from "./pages/Home";
import ItemDetail from "./pages/ItemDetail";
import Inbox      from "./pages/Inbox";
import Thread     from "./pages/Thread";
import Saved      from "./pages/Saved";
import "./App.css";

const PrivateRoute = ({ children }) => {
  const { token } = useContext(AuthContext);
  return token ? children : <Navigate to="/login" replace />;
};

const AppInner = () => (
  <Routes>
    <Route path="/login" element={<Login />} />
    <Route path="/" element={<PrivateRoute><Home /></PrivateRoute>} />
    <Route path="/item/:id" element={<PrivateRoute><ItemDetail /></PrivateRoute>} />
    <Route path="/inbox" element={<PrivateRoute><Inbox /></PrivateRoute>} />
    <Route path="/thread/:itemId/:otherUserId" element={<PrivateRoute><Thread /></PrivateRoute>} />
    <Route path="/saved" element={<PrivateRoute><Saved /></PrivateRoute>} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
);

const App = () => (
  <AuthProvider>
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  </AuthProvider>
);

export default App;
