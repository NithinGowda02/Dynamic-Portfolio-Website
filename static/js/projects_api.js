(() => {
  const root = document.querySelector('[data-projects-root]');
  if (!root) return;

  const escapeHtml = (value) => {
    const s = String(value ?? '');
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const render = (projects) => {
    if (!Array.isArray(projects) || projects.length === 0) {
      root.innerHTML = `
        <div class="empty-state">
          <p class="empty-state__text">No projects have been added yet. Add them to your database to display them here.</p>
        </div>
      `;
      return;
    }

    root.innerHTML = projects
      .map((p) => {
        const title = escapeHtml(p.title || '');
        const desc = escapeHtml(p.description || '');
        const cover = escapeHtml(p.cover_image_url || p.cover_image || '');
        const tech = String(p.tech_stack || '')
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean)
          .slice(0, 16);

        const techHtml = tech.length
          ? `<div class="project-card__tech-badges">${tech
              .map((t) => `<span class="tech-badge">${escapeHtml(t)}</span>`)
              .join('')}</div>`
          : '';

        const links = `
          <div class="project-card__links">
            ${p.github_link ? `<a href="${escapeHtml(p.github_link)}" class="btn btn--secondary btn--small" target="_blank" rel="noreferrer noopener">View Code</a>` : ''}
            ${p.live_demo ? `<a href="${escapeHtml(p.live_demo)}" class="btn btn--primary btn--small" target="_blank" rel="noreferrer noopener">Live Demo</a>` : ''}
          </div>
        `;

        return `
          <article class="project-card project-card--details" id="project-${Number(p.id) || 0}">
            ${cover ? `<div class="project-card__image"><img src="${cover}" alt="${title} screenshot"></div>` : ''}
            <h3 class="project-card__title">${title}</h3>
            <p class="project-card__copy">${desc}</p>
            ${techHtml}
            ${links}
          </article>
        `;
      })
      .join('');
  };

  fetch('/api/projects', { headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r)))
    .then(render)
    .catch(() => {
      // Keep server-rendered HTML as a fallback.
    });
})();

