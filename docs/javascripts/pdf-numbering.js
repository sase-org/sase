(function () {
  const chapters = {
    "/": 1,
    "/start/": 2,
    "/start/install/": 3,
    "/start/first-run/": 4,
    "/start/first-change/": 5,
    "/blog/posts/structured-agentic-software-engineering/": 6,
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
