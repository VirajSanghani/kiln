import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, clearToken, getToken, setToken } from "./api";

type User = { id: number; username: string; display_name: string; role: "operator" | "requester" };
type AuthCtx = {
  user: User | null;
  loading: boolean;
  login: (u: string, p: string) => Promise<User>;
  logout: () => void;
};

const Ctx = createContext<AuthCtx>(null as any);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api.get("/auth/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string) {
    const res = await api.login(username, password);
    setToken(res.access_token);
    setUser(res.user);
    return res.user as User;
  }

  function logout() {
    clearToken();
    setUser(null);
  }

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>;
}
