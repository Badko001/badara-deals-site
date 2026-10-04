const CABINS: Record<string, string> = {
  ECONOMY: "Economy",
  PREMIUM_ECONOMY: "Premium Economy",
  BUSINESS: "Business",
  FIRST: "La Première",
};

export const cabin = (value: string | null | undefined): string =>
  value ? (CABINS[value] ?? value) : "Inconnu";

/** null stays visibly "unknown" - never rendered as 0 or "no". */
export const unknown = <T,>(value: T | null | undefined, render: (v: T) => string): string =>
  value === null || value === undefined ? "Inconnu (non observé)" : render(value);

export const euros = (value: number | null | undefined): string =>
  unknown(value, (v) => `${v.toLocaleString("fr-FR")} €`);

export const miles = (value: number | null | undefined): string =>
  unknown(value, (v) => `${v.toLocaleString("fr-FR")} Miles`);

export const dateTime = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleString("fr-FR") : "—";

export const yesNo = (value: boolean | null | undefined): string =>
  unknown(value, (v) => (v ? "Oui" : "Non"));
