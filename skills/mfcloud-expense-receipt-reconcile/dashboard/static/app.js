(function () {
  const scripts = ["/static/js/common.js"];
  if (document.getElementById("run-form")) {
    scripts.push("/static/js/index.js");
  } else if (document.getElementById("exclude-section")) {
    scripts.push("/static/js/run.js");
  } else if (document.querySelector(".print-single") || document.getElementById("excluded-search")) {
    scripts.push("/static/js/excluded-pdfs.js");
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.body.appendChild(s);
    });
  }

  scripts.reduce((p, src) => p.then(() => loadScript(src)), Promise.resolve()).catch(() => {
    // Best effort compatibility shim; page still works when explicit scripts are used.
  });
})();
