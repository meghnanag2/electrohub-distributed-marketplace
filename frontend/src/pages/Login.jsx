import React, { useState, useContext } from "react";
import { useNavigate } from "react-router-dom";
import { AuthContext } from "../context/AuthContext";
import { login } from "../services/authService";

const Login = () => {
  const { setToken } = useContext(AuthContext);
  const navigate = useNavigate();
  const [email,    setEmail]    = useState("demo@electrohub.com");
  const [password, setPassword] = useState("password123");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const data = await login(email, password);
      setToken(data.access_token, data.user);
      navigate("/");
    } catch {
      setError("Invalid email or password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>ElectroHub</h1>
        <p className="subtitle">Buy &amp; sell electronics in your area</p>
        <form onSubmit={handleSubmit}>
          <input type="email" placeholder="Email" value={email}
            onChange={e => setEmail(e.target.value)} required />
          <input type="password" placeholder="Password" value={password}
            onChange={e => setPassword(e.target.value)} required />
          {error && <div className="error">{error}</div>}
          <button type="submit" disabled={loading}>
            {loading ? "Logging in…" : "Log In"}
          </button>
        </form>
        <div className="helper-text">Demo: demo@electrohub.com / password123</div>
      </div>
    </div>
  );
};

export default Login;
