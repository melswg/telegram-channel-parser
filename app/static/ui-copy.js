(() => {
  // Presentation only: values, credentials, code and link destinations stay intact.
  const excluded = "script, style, textarea, input, code, .secret-content, .topbar nav";
  function lowerStart(original) {
    return !original.includes(".") && original === original.toLocaleUpperCase("ru")
      ? original.toLocaleLowerCase("ru")
      : original.replace(/\p{L}/u, (letter) => letter.toLocaleLowerCase("ru"));
  }
  function format(node) {
    if (node.nodeType !== Node.TEXT_NODE || node.parentElement?.closest(excluded)) return;
    const original = node.nodeValue;
    if (!original || !/\p{L}/u.test(original)) return;
    const text = lowerStart(original);
    if (text !== original) node.nodeValue = text;
  }
  function visit(root) {
    if (root.nodeType === Node.TEXT_NODE) return format(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) format(walker.currentNode);
  }
  visit(document.body);
  function formatPlaceholder(field) {
    const original = field.getAttribute("placeholder");
    if (original && lowerStart(original) !== original) field.setAttribute("placeholder", lowerStart(original));
  }
  document.querySelectorAll("[placeholder]").forEach(formatPlaceholder);
  new MutationObserver((changes) => {
    for (const change of changes) {
      if (change.type === "attributes") formatPlaceholder(change.target);
      else if (change.type === "characterData") format(change.target);
      else change.addedNodes.forEach(visit);
    }
  }).observe(document.body, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:["placeholder"]});
})();
