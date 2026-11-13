/* Applies the stored theme choice before first paint (no flash). Mirrors src/shell/theme.ts;
   it is a separate file because the CSP allows scripts from this origin only (no inline script).
   The two colours are the page background of each theme (design/tokens.ts, held equal by a test);
   they go into the theme-color metas, so the browser's own bars match from the first frame. */
try {
  var theme = localStorage.getItem("bb.theme");
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
    var colour = theme === "dark" ? "#0D1218" : "#F3F7FB";
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (meta) {
      meta.setAttribute("content", colour);
    });
  }
} catch {
  /* private window or blocked site data: follow the system */
}
