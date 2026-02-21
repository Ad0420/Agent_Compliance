const API_KEY_STORAGE_KEY = "actionledger_api_key";
const IS_ADMIN_STORAGE_KEY = "actionledger_is_admin";

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(API_KEY_STORAGE_KEY);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE_KEY, key);
}

export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
  localStorage.removeItem(IS_ADMIN_STORAGE_KEY);
}

export function getIsAdmin(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(IS_ADMIN_STORAGE_KEY) === "true";
}

export function setIsAdmin(isAdmin: boolean): void {
  localStorage.setItem(IS_ADMIN_STORAGE_KEY, isAdmin ? "true" : "false");
}

export function getKeyPrefix(): string {
  const key = getApiKey();
  if (!key) return "";
  return key.substring(0, 16) + "...";
}
