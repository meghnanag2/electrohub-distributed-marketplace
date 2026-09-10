import axios from "axios";

// Empty string = same-origin (local dev via CRA proxy, or Nginx serving both
// frontend and backend). Set REACT_APP_API_URL when the frontend is deployed
// separately from the backend (e.g. Vercel frontend + GCP/Oracle backend).
const API_BASE_URL = process.env.REACT_APP_API_URL || "";

const api = axios.create({ baseURL: API_BASE_URL });

// Initialize token immediately from localStorage so first useEffect calls are authenticated
const _stored = localStorage.getItem("token");
if (_stored) api.defaults.headers.common["Authorization"] = `Bearer ${_stored}`;

export const setAuthToken = (token) => {
  if (token) {
    api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common["Authorization"];
  }
};

export { API_BASE_URL };
export default api;
