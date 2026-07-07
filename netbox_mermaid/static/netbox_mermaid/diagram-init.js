// SPDX-License-Identifier: AGPL-3.0-or-later
// Client-side render + controls for the SoT Mermaid diagram. Loaded as a static file (not inline)
// so it satisfies NetBox's strict Content-Security-Policy. Degrades gracefully: if the vendored
// mermaid.min.js is a stub / failed to load, the raw source <pre> stays visible and copy still works.
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }

  ready(function () {
    var srcEl = document.getElementById("mermaid-src");
    var canvas = document.getElementById("mermaid-canvas");
    var copyBtn = document.getElementById("copy-source");
    var toggleBtn = document.getElementById("toggle-source");
    if (!srcEl) {
      return;
    }
    var source = srcEl.textContent || "";

    var hasMermaid = typeof window.mermaid !== "undefined" && window.mermaid;
    if (hasMermaid && canvas) {
      var dark = document.documentElement.getAttribute("data-bs-theme") === "dark";
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: dark ? "dark" : "default",
        });
        canvas.textContent = source;
        window.mermaid.run({ nodes: [canvas] });
        srcEl.style.display = "none"; // rendered OK — hide raw source until toggled
      } catch (e) {
        // Parse/render failure: leave the raw source visible so the user still sees the diagram text.
        if (canvas) {
          canvas.style.display = "none";
        }
      }
    } else if (canvas) {
      // No mermaid available (offline stub): hide the empty canvas, keep the source visible.
      canvas.style.display = "none";
    }

    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(source).then(function () {
            copyBtn.textContent = "Copied!";
            setTimeout(function () {
              copyBtn.textContent = "Copy Mermaid source";
            }, 1500);
          });
        }
      });
    }

    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        srcEl.style.display = srcEl.style.display === "none" ? "block" : "none";
      });
    }
  });
})();
