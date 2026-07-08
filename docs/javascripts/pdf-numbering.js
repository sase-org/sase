(function () {
  const chapters = {
    "/": 1,
    "/blog/": 2,
    "/getting_started/": 3,
    "/ace/": 4,
    "/axe/": 5,
    "/sdd/": 6,
    "/xprompt/": 7,
    "/change_spec/": 8,
    "/beads/": 9,
    "/workflow_spec/": 10,
    "/workspace/": 11,
    "/mentors/": 12,
    "/commit_workflows/": 13,
    "/notifications/": 14,
    "/mobile_gateway/": 15,
    "/mobile_mvp_runbook/": 16,
    "/perf_runbook/": 17,
    "/telemetry/": 18,
    "/integrations/": 19,
    "/plugins/": 20,
    "/llms/": 21,
    "/vcs/": 22,
    "/rust_backend/": 23,
    "/configuration/": 24,
    "/query_language/": 25,
    "/project_spec/": 26,
    "/agent_images/": 27,
  };

  function normalizedPath() {
    const canonical = document.querySelector('link[rel="canonical"]');
    const href = canonical ? canonical.href : window.location.href;
    const url = new URL(href, window.location.href);
    let path = url.pathname || "/";

    if (path.endsWith("/index.html")) {
      path = path.slice(0, -"index.html".length);
    }

    if (!path.startsWith("/")) {
      path = "/" + path;
    }

    if (!path.endsWith("/")) {
      path += "/";
    }

    return path;
  }

  function prefixHeading(heading, number) {
    if (heading.dataset.pdfNumbered === "true") {
      return;
    }

    const prefix = document.createElement("span");
    prefix.className = "pdf-heading-number";
    prefix.textContent = number + " ";
    heading.insertBefore(prefix, heading.firstChild);
    heading.dataset.pdfNumbered = "true";
  }

  function render() {
    const chapter = chapters[normalizedPath()];
    if (!chapter) {
      return;
    }

    const headings = document.querySelectorAll(
      ".md-typeset h1, .md-typeset h2, .md-typeset h3",
    );
    let h2 = 0;
    let h3 = 0;

    headings.forEach((heading) => {
      if (heading.closest(".pdf-cover, .pdf-front-matter")) {
        return;
      }

      if (heading.tagName === "H1") {
        prefixHeading(heading, String(chapter));
        return;
      }

      if (heading.tagName === "H2") {
        h2 += 1;
        h3 = 0;
        prefixHeading(heading, chapter + "." + h2);
        return;
      }

      if (heading.tagName === "H3") {
        h3 += 1;
        prefixHeading(heading, chapter + "." + h2 + "." + h3);
      }
    });
  }

  window.MkDocsExporter = window.MkDocsExporter || {};
  const previousRender = window.MkDocsExporter.render;
  window.MkDocsExporter.render = async function (...args) {
    if (typeof previousRender === "function") {
      await previousRender.apply(this, args);
    }
    render();
  };
})();
