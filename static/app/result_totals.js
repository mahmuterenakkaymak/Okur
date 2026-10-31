// Money on the result view: Turkish format, and the sign written exactly once.
// A receipt prints a discount as "52,32-" and the validator accepts that as
// negative, so both signs of the same discount have to land on one "−52,32".
//
// ASSUMPTION: totals.iskonto is a discount, not a signed amount — the validator
// takes abs() of it too — so its line always shows a single minus, whichever
// way the receipt printed it.

const EKI = "−";

const MONEY = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

// Half a kuruş: below it nothing is left on screen, so no sign either.
const KURUS = 0.005;

/** Contract number as a usable float; anything missing or blurred reads 0. */
export function sayi(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** Amount with two decimals: "1.046,40", "−52,32". */
export function para(value) {
  const n = sayi(value);
  const text = MONEY.format(Math.abs(n));
  return n < 0 && Math.abs(n) >= KURUS ? `${EKI}${text}` : text;
}

/** Discount line: one minus for a discount, plain zero when there is none. */
export function iskontoPara(value) {
  const n = Math.abs(sayi(value));
  return n >= KURUS ? `${EKI}${MONEY.format(n)}` : MONEY.format(0);
}
