// What the interface calls this computer: "Mac", "PC" or "computer" (from the server, D-043).
let device = "computer";
let keychain = "system keyring";

export function setDevice(word: string | undefined, keychainName: string | undefined) {
  if (word) device = word;
  if (keychainName) keychain = keychainName;
}

/** "Mac" / "PC" / "computer" */
export function dev(): string {
  return device;
}

/** "Keychain" / "Windows Credential Manager" / "system keyring" */
export function keychainName(): string {
  return keychain;
}
