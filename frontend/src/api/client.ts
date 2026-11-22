import createClient from "openapi-fetch";
import { useQuery } from "@tanstack/react-query";
import type { components, paths } from "./generated/schema";
export type Schema = components["schemas"];
export const api = createClient<paths>({});
export async function read<T>(
  promise: Promise<{ data?: T; response: Response }>,
): Promise<T> {
  const { data, response } = await promise;
  if (!response.ok || data === undefined)
    throw new Error(`Request failed (HTTP ${String(response.status)})`);
  return data;
}
export const useRadar = () =>
  useQuery({
    queryKey: ["insider", "radar"],
    queryFn: () => read(api.GET("/api/v1/insider/radar")),
  });
export const useRings = () =>
  useQuery({
    queryKey: ["mule", "rings"],
    queryFn: () => read(api.GET("/api/v1/mule/rings")),
  });
export const useInfo = () =>
  useQuery({
    queryKey: ["info"],
    queryFn: () => read(api.GET("/api/v1/system/info")),
  });
export const useHealth = () =>
  useQuery({
    queryKey: ["health"],
    queryFn: () => read(api.GET("/api/v1/health")),
    refetchInterval: 30000,
  });
