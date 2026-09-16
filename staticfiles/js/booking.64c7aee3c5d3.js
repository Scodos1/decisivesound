document.addEventListener("DOMContentLoaded", () => {

  /* ============================================================
     PRICING CONSTANTS
     Standard rates — Lagos state only.
     Service charge outside Lagos is quoted separately.
  ============================================================ */
  const RATE_PER_HEADSET = 1500;   // ₦ flat rate per headset
  const SERVICE_CHARGE   = 80000;  // ₦ transport/logistics — Lagos state only
  const CAUTION_FEE      = 80000;  // ₦ upfront deposit, refundable

  /* ============================================================
     LIVE QUOTE CALCULATOR  (headsets slider + location dropdown)
  ============================================================ */
  const headsetsInput   = document.querySelector("#calc-headsets");
  const locationInput   = document.querySelector("#calc-location");
  const headsetsValEl   = document.querySelector("#calc-headsets-value");
  const headsetsVal2El  = document.querySelector("#calc-headsets-value2");
  const lineRentalEl    = document.querySelector("#line-rental");
  const lineTravelEl    = document.querySelector("#line-travel");
  const lineTravelRow   = document.querySelector("#line-travel-row");
  const lineCautionEl   = document.querySelector("#line-caution");
  const lineTotalEl     = document.querySelector("#line-total");
  const customQuoteNote = document.querySelector("#custom-quote-note");

  const LAGOS_CALC_OPTS = ["Lagos"];

  function fmt(n) {
    return "₦" + n.toLocaleString("en-NG");
  }

  function recalc() {
    if (!headsetsInput || !locationInput) return;

    const headsets = Number(headsetsInput.value) || 0;
    const location = locationInput.value;
    const inLagos  = LAGOS_CALC_OPTS.includes(location);
    const rental   = headsets * RATE_PER_HEADSET;
    const total    = rental + SERVICE_CHARGE + CAUTION_FEE;

    if (headsetsValEl)  headsetsValEl.textContent  = headsets;
    if (headsetsVal2El) headsetsVal2El.textContent = headsets;
    if (lineRentalEl)   lineRentalEl.textContent   = fmt(rental);
    if (lineCautionEl)  lineCautionEl.textContent  = fmt(CAUTION_FEE);

    if (lineTravelRow) lineTravelRow.style.display = "flex";
    if (lineTravelEl)  lineTravelEl.textContent = inLagos ? fmt(SERVICE_CHARGE) : "To be confirmed";

    if (lineTotalEl)   lineTotalEl.textContent = inLagos ? fmt(total) : "Contact us";
    if (customQuoteNote) customQuoteNote.style.display = inLagos ? "none" : "flex";
  }

  if (headsetsInput && locationInput) {
    [headsetsInput, locationInput].forEach(el => el.addEventListener("input", recalc));
    recalc();
  }

  /* ============================================================
     STATE DROPDOWN — live service charge indicator in the form
  ============================================================ */
  const stateSelect   = document.querySelector("#f-state");
  const chargeNote    = document.querySelector("#state-charge-note");
  const chargeIcon    = document.querySelector("#state-charge-icon");
  const chargeText    = document.querySelector("#state-charge-text");

  function updateStateIndicator() {
    if (!stateSelect || !chargeNote) return;
    const state = stateSelect.value;
    if (!state) { chargeNote.style.display = "none"; return; }

    const isLagos = state === "Lagos";

    chargeNote.style.display     = "flex";
    chargeNote.style.background  = isLagos
      ? "rgba(0,228,115,0.08)"
      : "rgba(255,203,77,0.08)";
    chargeNote.style.border      = isLagos
      ? "1px solid rgba(0,228,115,0.25)"
      : "1px solid rgba(255,203,77,0.28)";

    chargeIcon.textContent       = isLagos ? "check_circle" : "info";
    chargeIcon.style.color       = isLagos ? "var(--tertiary)" : "#ffcb4d";

    chargeText.innerHTML = isLagos
      ? `<strong style="color:var(--on-surface);">Service charge: ₦80,000</strong>
         <span style="color:var(--on-surface-variant);"> — covers transport & logistics within Lagos State.</span>`
      : `<strong style="color:var(--on-surface);">Service charge: To be confirmed</strong>
         <span style="color:var(--on-surface-variant);"> — pricing outside Lagos State is quoted separately. We'll confirm the exact charge when we review your booking.</span>`;
  }

  if (stateSelect) {
    stateSelect.addEventListener("change", updateStateIndicator);
    updateStateIndicator();
  }

  /* ============================================================
     BOOKING FORM — now a normal Django POST (see booking/views.py).
     Django validates + saves the booking and redirects to the
     booking_success page, which handles the WhatsApp handoff.
     No submit-time JS is needed here any more.
  ============================================================ */
});
