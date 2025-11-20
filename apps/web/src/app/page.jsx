"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getStatus,
  getOpenPositions,
  getPnlSummary,
  getApiBaseUrl,
  login,
  logout,
  getCurrentUser,
} from "../utils/apiClient";

const numberFormatter = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export default function DashboardPage() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [loginLoading, setLoginLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [pnlSummary, setPnlSummary] = useState(null);
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [statusRes, pnlRes, positionsRes] = await Promise.all([
        getStatus(),
        getPnlSummary(),
        getOpenPositions(),
      ]);
      setStatus(statusRes);
      setPnlSummary(pnlRes);
      setPositions(positionsRes.positions || []);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    async function checkAuth() {
      setAuthLoading(true);
      setAuthError("");
      try {
        const data = await getCurrentUser();
        if (!ignore) {
          setUser(data.user);
        }
      } catch {
        if (!ignore) {
          setUser(null);
        }
      } finally {
        if (!ignore) {
          setAuthLoading(false);
        }
      }
    }
    checkAuth();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!user) {
      setStatus(null);
      setPnlSummary(null);
      setPositions([]);
      setLoading(false);
      return;
    }

    fetchDashboard();
    const timer = setInterval(fetchDashboard, 10000);
    return () => clearInterval(timer);
  }, [user, fetchDashboard]);

  const handleLogin = async (event) => {
    event.preventDefault();
    setLoginLoading(true);
    setAuthError("");
    try {
      const loggedUser = await login(loginForm.username, loginForm.password);
      setUser(loggedUser);
      setLoginForm({ username: "", password: "" });
    } catch (err) {
      console.error(err);
      setAuthError(err instanceof Error ? err.message : "Giriş başarısız");
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch (err) {
      console.error(err);
    } finally {
      setUser(null);
      setStatus(null);
      setPnlSummary(null);
      setPositions([]);
    }
  };

  const isHealthy = status?.health === "ok";

  if (authLoading) {
    return (
      <main style={styles.container}>
        <p>Oturum kontrol ediliyor...</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main style={styles.container}>
        <section style={styles.authWrapper}>
          <div style={styles.authCard}>
            <h1 style={styles.authTitle}>Futures Bot Paneli</h1>
            <p style={styles.subtitle}>
              Backend API: <code>{getApiBaseUrl()}</code>
            </p>
            <form style={styles.authForm} onSubmit={handleLogin}>
              <label style={styles.authLabel}>
                Kullanıcı Adı
                <input
                  style={styles.authInput}
                  type="text"
                  value={loginForm.username}
                  onChange={(e) =>
                    setLoginForm((prev) => ({ ...prev, username: e.target.value }))
                  }
                  required
                />
              </label>
              <label style={styles.authLabel}>
                Şifre
                <input
                  style={styles.authInput}
                  type="password"
                  value={loginForm.password}
                  onChange={(e) =>
                    setLoginForm((prev) => ({ ...prev, password: e.target.value }))
                  }
                  required
                />
              </label>
              {authError && <p style={styles.error}>{authError}</p>}
              <button style={styles.primaryButton} type="submit" disabled={loginLoading}>
                {loginLoading ? "Giriş yapılıyor..." : "Giriş Yap"}
              </button>
            </form>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main style={styles.container}>
      <header style={styles.header}>
        <div>
          <h1 style={styles.title}>Futures Bot Dashboard</h1>
          <p style={styles.subtitle}>
            Backend API: <code>{getApiBaseUrl()}</code>
          </p>
        </div>
        <div style={styles.userBox}>
          <div>
            <p style={styles.userName}>Hoş geldin, {user.username}</p>
            <small style={styles.userRole}>Rol: {user.role}</small>
          </div>
          <button style={styles.refreshButton} onClick={fetchDashboard}>
            Yenile
          </button>
          <button style={styles.logoutButton} onClick={handleLogout}>
            Çıkış Yap
          </button>
        </div>
      </header>

      {loading && <p>Veriler yükleniyor...</p>}
      {error && <p style={styles.error}>{error}</p>}

      <section style={styles.grid}>
        <div style={styles.card}>
          <h3>Bot Durumu</h3>
          <p>
            <strong>Versiyon:</strong> {status?.bot_version || "-"}
          </p>
          <p>
            <strong>Health:</strong>{" "}
            <span style={isHealthy ? styles.badgeSuccess : styles.badgeDanger}>
              {status?.health || "bilinmiyor"}
            </span>
          </p>
        </div>

        <div style={styles.card}>
          <h3>Günlük Realized PnL</h3>
          <p style={styles.kpi}>
            {pnlSummary
              ? `${numberFormatter.format(pnlSummary.daily_realized_pnl)} USDT`
              : "-"}
          </p>
        </div>

        <div style={styles.card}>
          <h3>Toplam Realized PnL</h3>
          <p style={styles.kpi}>
            {pnlSummary
              ? `${numberFormatter.format(pnlSummary.total_realized_pnl)} USDT`
              : "-"}
          </p>
        </div>

        <div style={styles.card}>
          <h3>Genel ROI</h3>
          <p style={styles.kpi}>
            {pnlSummary
              ? `${numberFormatter.format(pnlSummary.overall_roi)} %`
              : "-"}
          </p>
        </div>
      </section>

      <section style={styles.tableSection}>
        <div style={styles.tableHeader}>
          <h2>Açık Pozisyonlar</h2>
          <span>{positions.length} kayıt</span>
        </div>
        <div style={styles.tableWrapper}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th>Sembol</th>
                <th>Yön</th>
                <th>Giriş</th>
                <th>Adet</th>
                <th>SL Fiyat</th>
                <th>SL ROE</th>
                <th>Peak ROE</th>
                <th>Peak PnL</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && (
                <tr>
                  <td colSpan={8} style={styles.emptyCell}>
                    Açık pozisyon yok
                  </td>
                </tr>
              )}
              {positions.map((pos) => (
                <tr key={`${pos.symbol}-${pos.position_side}`}>
                  <td>{pos.symbol}</td>
                  <td>
                    <span
                      style={
                        pos.position_side === "LONG"
                          ? styles.badgeSuccess
                          : styles.badgeDanger
                      }
                    >
                      {pos.position_side}
                    </span>
                  </td>
                  <td>{numberFormatter.format(pos.entry_price || 0)}</td>
                  <td>{numberFormatter.format(pos.quantity || 0)}</td>
                  <td>
                    {pos.stop_loss_price
                      ? numberFormatter.format(pos.stop_loss_price)
                      : "-"}
                  </td>
                  <td>
                    {pos.stop_loss_roe
                      ? `${numberFormatter.format(pos.stop_loss_roe)} %`
                      : "-"}
                  </td>
                  <td>
                    {pos.peak_roe
                      ? `${numberFormatter.format(pos.peak_roe)} %`
                      : "-"}
                  </td>
                  <td>
                    {pos.peak_pnl
                      ? `${numberFormatter.format(pos.peak_pnl)} USDT`
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

const styles = {
  container: {
    minHeight: "100vh",
    padding: "2rem",
    backgroundColor: "#0b0f1a",
    color: "#f1f5f9",
    fontFamily: "'Inter', system-ui, sans-serif",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "1.5rem",
  },
  title: {
    fontSize: "2rem",
    margin: 0,
  },
  subtitle: {
    margin: 0,
    color: "#94a3b8",
  },
  refreshButton: {
    backgroundColor: "#f3ba2f",
    color: "#0f172a",
    border: "none",
    borderRadius: "999px",
    padding: "0.6rem 1.4rem",
    fontWeight: 600,
    cursor: "pointer",
  },
  error: {
    color: "#f87171",
    marginTop: "0.5rem",
    marginBottom: "1rem",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: "1rem",
    marginBottom: "2rem",
  },
  card: {
    backgroundColor: "#161b2b",
    borderRadius: "1rem",
    padding: "1rem",
    border: "1px solid rgba(255,255,255,0.05)",
  },
  kpi: {
    fontSize: "1.8rem",
    fontWeight: 700,
    margin: "0.5rem 0 0",
  },
  badgeSuccess: {
    display: "inline-block",
    padding: "0.2rem 0.6rem",
    borderRadius: "999px",
    backgroundColor: "rgba(34,197,94,0.15)",
    color: "#22c55e",
    fontWeight: 600,
  },
  badgeDanger: {
    display: "inline-block",
    padding: "0.2rem 0.6rem",
    borderRadius: "999px",
    backgroundColor: "rgba(239,68,68,0.15)",
    color: "#ef4444",
    fontWeight: 600,
  },
  tableSection: {
    backgroundColor: "#111425",
    borderRadius: "1.5rem",
    padding: "1.5rem",
    border: "1px solid rgba(255,255,255,0.08)",
  },
  tableHeader: {
    display: "flex",
    justifyContent: "space-between",
    marginBottom: "1rem",
    alignItems: "center",
  },
  tableWrapper: {
    overflowX: "auto",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
  },
  emptyCell: {
    textAlign: "center",
    padding: "1.5rem",
    color: "#94a3b8",
  },
  authWrapper: {
    width: "100%",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    minHeight: "60vh",
  },
  authCard: {
    width: "100%",
    maxWidth: "420px",
    backgroundColor: "#111425",
    borderRadius: "1.5rem",
    padding: "2rem",
    border: "1px solid rgba(255,255,255,0.08)",
    boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
  },
  authTitle: {
    margin: "0 0 0.5rem",
    fontSize: "1.8rem",
  },
  authForm: {
    display: "flex",
    flexDirection: "column",
    gap: "1rem",
    marginTop: "1.5rem",
  },
  authLabel: {
    display: "flex",
    flexDirection: "column",
    gap: "0.4rem",
    fontSize: "0.9rem",
  },
  authInput: {
    borderRadius: "0.8rem",
    border: "1px solid rgba(255,255,255,0.1)",
    padding: "0.75rem 1rem",
    backgroundColor: "#0f1320",
    color: "#f1f5f9",
  },
  primaryButton: {
    backgroundColor: "#f3ba2f",
    color: "#0f172a",
    border: "none",
    borderRadius: "999px",
    padding: "0.8rem 1.4rem",
    fontWeight: 600,
    cursor: "pointer",
  },
  userBox: {
    display: "flex",
    alignItems: "center",
    gap: "1rem",
  },
  userName: {
    margin: 0,
    fontWeight: 600,
  },
  userRole: {
    color: "#94a3b8",
  },
  logoutButton: {
    backgroundColor: "transparent",
    color: "#f87171",
    border: "1px solid rgba(248,113,113,0.4)",
    borderRadius: "999px",
    padding: "0.5rem 1.2rem",
    fontWeight: 600,
    cursor: "pointer",
  },
};

