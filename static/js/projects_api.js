(() => {
  const root = document.querySelector('[data-projects-root]');
  if (!root) return;

  /* ── Helpers ─────────────────────────────────────────────── */
  const esc = (v) => {
    const s = String(v ?? '');
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  /* ── Build gallery HTML (same structure as homepage) ──────── */
  const buildGallery = (imgs, title) => {
    if (!imgs.length) return '';

    const slides = imgs
      .map(
        (src, i) => `
        <div class="proj-gallery__slide" data-gallery-slide>
          <img src="${esc(src)}" alt="${esc(title)} screenshot ${i + 1}" loading="lazy">
        </div>`
      )
      .join('');

    const thumbs =
      imgs.length > 1
        ? `<div class="proj-gallery__thumbs" data-gallery-thumbs>
            ${imgs
              .map(
                (src, i) => `
              <button class="proj-gallery__thumb${i === 0 ? ' is-active' : ''}"
                      type="button" data-gallery-thumb="${i}"
                      aria-label="Go to screenshot ${i + 1}">
                <img src="${esc(src)}" alt="${esc(title)} thumbnail ${i + 1}" loading="lazy">
              </button>`
              )
              .join('')}
           </div>`
        : '';

    return `
      <div class="project-card__image">
        <div class="proj-gallery proj-gallery--large" data-gallery>
          <button class="proj-gallery__nav proj-gallery__nav--prev"
                  type="button" aria-label="Previous image" data-gallery-prev>&lsaquo;</button>
          <button class="proj-gallery__nav proj-gallery__nav--next"
                  type="button" aria-label="Next image"  data-gallery-next>&rsaquo;</button>
          <div class="proj-gallery__viewport" data-gallery-viewport>
            <div class="proj-gallery__track" data-gallery-track>
              ${slides}
            </div>
          </div>
          <div class="proj-gallery__dots" data-gallery-dots></div>
          ${thumbs}
        </div>
      </div>`;
  };

  /* ── Render all project cards ─────────────────────────────── */
  const render = (projects) => {
    if (!Array.isArray(projects) || projects.length === 0) {
      root.innerHTML = `
        <div class="empty-state">
          <p class="empty-state__text">No projects have been added yet.
            Add them to your database to display them here.</p>
        </div>`;
      return;
    }

    root.innerHTML = projects
      .map((p) => {
        const title = esc(p.title || '');
        const desc  = esc(p.description || '');

        /* Collect all image URLs — support both array and single cover */
        const imgs = Array.isArray(p.images) && p.images.length
          ? p.images
          : (p.cover_image_url || p.cover_image)
            ? [p.cover_image_url || p.cover_image]
            : [];

        const tech = String(p.tech_stack || '')
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean)
          .slice(0, 16);

        const techHtml = tech.length
          ? `<div class="project-card__tech-badges">
               ${tech.map((t) => `<span class="tech-badge">${esc(t)}</span>`).join('')}
             </div>`
          : '';

        const links = `
          <div class="project-card__links">
            ${p.github_link
              ? `<a href="${esc(p.github_link)}" class="btn btn--secondary btn--small"
                    target="_blank" rel="noreferrer noopener">View Code</a>`
              : ''}
            ${p.live_demo
              ? `<a href="${esc(p.live_demo)}" class="btn btn--primary btn--small"
                    target="_blank" rel="noreferrer noopener">Live Demo</a>`
              : ''}
          </div>`;

        return `
          <article class="project-card project-card--details"
                   id="project-${Number(p.id) || 0}">
            ${buildGallery(imgs, p.title || '')}
            <div class="project-card__content">
              <h3 class="project-card__title">${title}</h3>
              <p class="project-card__copy">${desc}</p>
              ${techHtml}
              ${links}
            </div>
          </article>`;
      })
      .join('');

    /* ── Initialize all galleries after HTML is injected ─────── */
    initGalleries(root);
  };

  /* ── Gallery slider initializer ───────────────────────────── */
  const initGalleries = (scope) => {
    scope.querySelectorAll('[data-gallery]').forEach((gallery) => {
      const track    = gallery.querySelector('[data-gallery-track]');
      const slides   = gallery.querySelectorAll('[data-gallery-slide]');
      const dotsWrap = gallery.querySelector('[data-gallery-dots]');
      const prevBtn  = gallery.querySelector('[data-gallery-prev]');
      const nextBtn  = gallery.querySelector('[data-gallery-next]');
      const thumbsWrap = gallery.querySelector('[data-gallery-thumbs]');

      if (!track || slides.length === 0) return;

      let current = 0;
      const total = slides.length;

      /* Build dot indicators */
      const dots = [];
      if (dotsWrap && total > 1) {
        for (let i = 0; i < total; i++) {
          const d = document.createElement('span');
          d.className = 'slider-dot' + (i === 0 ? ' active' : '');
          d.addEventListener('click', () => goTo(i));
          dotsWrap.appendChild(d);
          dots.push(d);
        }
      }

      /* Collect thumb buttons */
      const thumbBtns = thumbsWrap
        ? Array.from(thumbsWrap.querySelectorAll('[data-gallery-thumb]'))
        : [];

      const goTo = (index) => {
        current = (index + total) % total;
        track.style.transform = `translateX(-${current * 100}%)`;

        dots.forEach((d, i) =>
          d.classList.toggle('active', i === current)
        );
        thumbBtns.forEach((b) =>
          b.classList.toggle('is-active', Number(b.dataset.galleryThumb) === current)
        );
      };

      /* Nav arrows */
      if (prevBtn) prevBtn.addEventListener('click', () => goTo(current - 1));
      if (nextBtn) nextBtn.addEventListener('click', () => goTo(current + 1));

      /* Thumb clicks */
      thumbBtns.forEach((b) =>
        b.addEventListener('click', () => goTo(Number(b.dataset.galleryThumb)))
      );

      /* Touch / swipe support */
      let touchStartX = 0;
      gallery.addEventListener('touchstart', (e) => {
        touchStartX = e.touches[0].clientX;
      }, { passive: true });
      gallery.addEventListener('touchend', (e) => {
        const diff = touchStartX - e.changedTouches[0].clientX;
        if (Math.abs(diff) > 40) goTo(diff > 0 ? current + 1 : current - 1);
      }, { passive: true });

      /* Auto-advance (pauses on hover) */
      if (total > 1) {
        let timer = setInterval(() => goTo(current + 1), 4000);
        gallery.addEventListener('mouseenter', () => clearInterval(timer));
        gallery.addEventListener('mouseleave', () => {
          timer = setInterval(() => goTo(current + 1), 4000);
        });
      }

      goTo(0); /* initialize position */
    });
  };

  /* ── Fetch & render ───────────────────────────────────────── */
  fetch('/api/projects', { headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r)))
    .then(render)
    .catch(() => {
      /* API failed — keep the server-rendered Jinja HTML as fallback,
         but still initialize any galleries already in the DOM. */
      initGalleries(root);
    });
})();