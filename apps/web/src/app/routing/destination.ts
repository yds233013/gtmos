/** "team:Enterprise NA" → "Enterprise NA pool"; "user:<id>" → the user's name. */
export function destinationLabel(dest: string, userNames: Record<string, string>): string {
  const [kind, ...rest] = dest.split(":");
  const value = rest.join(":");
  if (kind === "team") return `${value} pool`;
  if (kind === "user") return userNames[value] ?? "Named user";
  return dest;
}
