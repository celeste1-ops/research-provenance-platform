import { lang } from "./i18n";

// What the interface calls this computer: "Mac", "PC" or "computer" (from the server, D-043).
let device = "computer";
let keychain = "system keyring";

export function setDevice(word: string | undefined, keychainName: string | undefined) {
  if (word) device = word;
  if (keychainName) keychain = keychainName;
}

const ZH_DEVICE: Record<string, string> = { Mac: "Mac", PC: "电脑", computer: "电脑" };
const ZH_KEYCHAIN: Record<string, string> = {
  Keychain: "钥匙串",
  "Windows Credential Manager": "Windows 凭据管理器",
  "system keyring": "系统密钥环",
};

/** "Mac" / "PC" / "computer" (Chinese: "Mac" / "电脑") */
export function dev(): string {
  return lang() === "zh" ? (ZH_DEVICE[device] ?? "电脑") : device;
}

/** "Keychain" / "Windows Credential Manager" / "system keyring" */
export function keychainName(): string {
  return lang() === "zh" ? (ZH_KEYCHAIN[keychain] ?? keychain) : keychain;
}
