/* Pricing page: yearly/monthly switch and where the buttons lead.
   BUY_URL / WAITLIST_URL are the only things to change when the store is set
   up (see docs/BUSINESS.md → "Taking payments"). */
(function () {
  "use strict";
  const BUY_URL = {
    year: "https://github.com/SoaOaoS/mav/issues/new?labels=connect&title=Mav%20Connect%20%E2%80%94%20yearly",
    month: "https://github.com/SoaOaoS/mav/issues/new?labels=connect&title=Mav%20Connect%20%E2%80%94%20monthly",
  };
  const BUSINESS_URL =
    "https://github.com/SoaOaoS/mav/issues/new?labels=business&title=Mav%20for%20Business";
  const WAITLIST_URL =
    "https://github.com/SoaOaoS/mav/issues/new?labels=cloud&title=Mav%20Cloud%20waitlist";

  function setBilling(period) {
    document.querySelectorAll("[data-billing]").forEach((b) =>
      b.classList.toggle("is-active", b.dataset.billing === period),
    );
    document.querySelectorAll("[data-price-year]").forEach((el) => {
      el.textContent = el.dataset[period === "year" ? "priceYear" : "priceMonth"];
    });
    document.querySelectorAll("[data-per-year]").forEach((el) => {
      el.textContent = el.dataset[period === "year" ? "perYear" : "perMonth"];
    });
    document.querySelectorAll("[data-buy]").forEach((a) => {
      a.href = BUY_URL[period];
      a.target = "_blank";
      a.rel = "noopener";
    });
  }
  document.querySelectorAll("[data-billing]").forEach((b) =>
    b.addEventListener("click", () => setBilling(b.dataset.billing)),
  );
  document.querySelectorAll("[data-waitlist]").forEach((a) => {
    a.href = WAITLIST_URL;
    a.target = "_blank";
    a.rel = "noopener";
  });
  document.querySelectorAll("[data-business]").forEach((a) => {
    a.href = BUSINESS_URL;
    a.target = "_blank";
    a.rel = "noopener";
  });
  setBilling("year");
})();
