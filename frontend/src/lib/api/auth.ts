import type { LoginRequest, TokenPairDTO, UserDTO } from "@/types/api";
import { apiClient } from "./client";

export async function login(request: LoginRequest): Promise<TokenPairDTO> {
  const response = await apiClient.post<TokenPairDTO>("/auth/login", request);
  return response.data;
}

export async function logout(refreshToken: string): Promise<void> {
  await apiClient.post("/auth/logout", { refresh_token: refreshToken });
}

export async function getCurrentUser(): Promise<UserDTO> {
  const response = await apiClient.get<UserDTO>("/auth/me");
  return response.data;
}
