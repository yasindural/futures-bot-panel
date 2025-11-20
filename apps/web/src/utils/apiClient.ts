const DEFAULT_BASE_URL = "http://localhost:5000";

const API_BASE_URL =
  import.meta.env?.VITE_API_BASE_URL?.replace(/\/$/, "") || DEFAULT_BASE_URL;

async function requestRaw(path: string, init?: RequestInit): Promise<any> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    credentials: "include",
    ...init,
  });

  const text = await response.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(text || `Request failed with ${response.status}`);
  }

  if (!response.ok) {
    const msg = data?.message || text || `Request failed with ${response.status}`;
    throw new Error(msg);
  }

  if (data && typeof data === "object" && "status" in data && data.status !== "ok") {
    throw new Error(data.message || "API error");
  }

  return data;
}

export type BotStatusResponse = {
  bot_version: string;
  health: string;
  config?: Record<string, unknown>;
};

export type AuthUser = {
  username: string;
  role: string;
};

export type Position = {
  state_key: string;
  symbol: string;
  position_side: "LONG" | "SHORT";
  entry_price: number;
  quantity: number;
  stop_loss_price: number;
  stop_loss_roe: number;
  peak_roe: number;
  peak_pnl: number;
  leverage: number;
  margin: number;
  opened_at: string;
};

export type OpenPositionsResponse = {
  positions: Position[];
};

export type PnlSummaryResponse = {
  daily_realized_pnl: number;
  total_realized_pnl: number;
  overall_roi: number;
};

export async function login(username: string, password: string): Promise<AuthUser> {
  const data = await requestRaw("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  return data.user;
}

export async function logout(): Promise<void> {
  await requestRaw("/api/auth/logout", { method: "POST" });
}

export async function getCurrentUser(): Promise<{ user: AuthUser }> {
  const data = await requestRaw("/api/auth/me");
  return { user: data.user as AuthUser };
}

export async function getStatus(): Promise<BotStatusResponse> {
  const data = await requestRaw("/api/status");
  return {
    bot_version: data.bot_version,
    health: data.health,
    config: data.config,
  };
}

export async function getOpenPositions(): Promise<OpenPositionsResponse> {
  const data = await requestRaw("/api/open-positions");
  const raw = data.positions || [];

  const positions: Position[] = raw.map((p: any) => ({
    state_key: p.state_key,
    symbol: p.symbol,
    position_side: p.position_side,
    entry_price: p.entry,
    quantity: p.qty,
    stop_loss_price: p.sl,
    stop_loss_roe: p.sl_roe,
    peak_roe: p.peak_roe,
    peak_pnl: p.peak_pnl,
    leverage: p.leverage,
    margin: p.margin,
    opened_at: p.opened_at,
  }));

  return { positions };
}

export async function getPnlSummary(): Promise<PnlSummaryResponse> {
  const data = await requestRaw("/api/pnl/summary");
  return {
    daily_realized_pnl: data.daily_realized_pnl ?? 0,
    total_realized_pnl: data.total_realized_pnl ?? 0,
    overall_roi: data.overall_roi ?? 0,
  };
}

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

