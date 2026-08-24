export const STUDIO_PATH = import.meta.env.BASE_URL || "/";
export const DEFAULT_CONTROL_PLANE_ORIGIN = "http://127.0.0.1:8000";

export function isLoopbackHost(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
}
