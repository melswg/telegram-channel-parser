(() => {
  const canvas = document.querySelector("canvas.footer-wave");
  if (!canvas) return;
  const context = canvas.getContext("2d", {alpha: false});
  if (!context) return;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const colors = getComputedStyle(canvas);
  const background = colors.getPropertyValue("--red").trim();
  const foreground = colors.getPropertyValue("--white").trim();
  // Ordered dithering keeps the transition stable instead of random flicker.
  const bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const pitch = 9;
  const square = 5;
  const frameInterval = 1000 / 30;
  let visible = false;
  let frame = 0;
  let previousTime = 0;
  let phase = 0;

  function paint() {
    const width = canvas.width;
    const height = canvas.height;
    context.fillStyle = background;
    context.fillRect(0, 0, width, height);
    context.fillStyle = foreground;
    context.beginPath();
    for (let column = 0, x = 0; x < width; column++, x += pitch) {
      const wave = Math.sin(x / 115 - phase) * height * .16
        + Math.sin(x / 63 + phase * .65) * height * .055;
      const surface = height * .48 + wave;
      for (let row = 0, y = 0; y < height; row++, y += pitch) {
        const density = (y - surface) / (height * .28) + .5;
        const threshold = (bayer[(row % 4) * 4 + column % 4] + .5) / 16;
        if (density > threshold) context.rect(x, y, square, square);
      }
    }
    // One fill for the entire grid; no images, SVG filters or per-pixel DOM.
    context.fill();
  }

  function tick(time) {
    if (!previousTime || time - previousTime >= frameInterval) {
      if (previousTime) phase += Math.min(time - previousTime, 100) * .00065;
      previousTime = time;
      paint();
    }
    frame = requestAnimationFrame(tick);
  }

  function update() {
    cancelAnimationFrame(frame);
    previousTime = 0;
    if (visible && !document.hidden && !reducedMotion.matches) {
      frame = requestAnimationFrame(tick);
    }
  }

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    // Decorative pixels need no Retina-sized backing buffer.
    const width = Math.max(1, Math.min(1600, Math.round(bounds.width)));
    const height = Math.max(1, Math.round(bounds.height));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    paint();
  }

  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    update();
  }).observe(canvas);
  reducedMotion.addEventListener("change", update);
  document.addEventListener("visibilitychange", update);
  resize();
})();
