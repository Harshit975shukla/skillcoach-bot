(() => {
  "use strict";
  const status = document.getElementById("join-status");
  const link = document.getElementById("request-access");
  fetch("/join/config", {cache: "no-store", credentials: "omit"})
    .then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Access requests are temporarily unavailable.");
      if (!data.available) {
        status.textContent = "Public requests are currently closed. Ask the owner for an invitation.";
        return;
      }
      if (!/^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}\?start=request$/.test(data.telegram_url)) {
        throw new Error("The bot link could not be verified. Try again later.");
      }
      link.href = data.telegram_url;
      link.hidden = false;
      status.textContent = "Requests are open. Only owner approval grants coaching access.";
    })
    .catch(error => {
      status.textContent = error.message || "Could not load access requests. Reload to retry.";
      status.classList.add("error");
    });
})();
