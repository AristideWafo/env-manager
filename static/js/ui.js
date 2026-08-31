(function () {
  "use strict";

  const ICONS = {
    success: "M9 12.75l2.25 2.25L15 9m6 3a9 9 0 11-18 0 9 9 0 0118 0z",
    error: "M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
    warning: "M12 9v3.75m9.303 3.376c.866 1.5-.217 3.374-1.948 3.374H4.645c-1.73 0-2.813-1.874-1.948-3.374L10.053 3.38c.865-1.5 3.03-1.5 3.896 0l7.354 12.746zM12 15.75h.008v.008H12v-.008z",
  };

  function alertIcon(tone) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("fill", "none");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("stroke-width", "1.5");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("class", "w-5 h-5 shrink-0 mt-0.5");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("d", ICONS[tone] || ICONS.success);
    svg.appendChild(path);
    return svg;
  }

  window.showAlert = function showAlert(target, tone, message) {
    if (!target) return;
    const alert = document.createElement("div");
    alert.className = `alert alert-${tone}`;
    alert.setAttribute("role", "status");
    alert.appendChild(alertIcon(tone));
    const copy = document.createElement("div");
    copy.textContent = message;
    alert.appendChild(copy);
    target.replaceChildren(alert);
  };
})();
