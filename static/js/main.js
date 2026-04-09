document.body.classList.add('nav-js');

const navToggle = document.getElementById('navToggle');
const mainNav = document.getElementById('mainNav');
const navList = document.querySelector('.nav__list');

if (navToggle && mainNav && navList) {
  const setNavOpen = (open) => {
    navList.classList.toggle('open', open);
    navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.body.classList.toggle('nav-open', open);
  };

  navToggle.addEventListener('click', () => {
    setNavOpen(!navList.classList.contains('open'));
  });

  // Close mobile menu when clicking on a navigation link
  navList.addEventListener('click', (event) => {
    if (event.target.closest('.nav__link')) setNavOpen(false);
  });

  // Close on outside click
  document.addEventListener('click', (event) => {
    if (!navList.classList.contains('open')) return;
    if (navToggle.contains(event.target)) return;
    if (mainNav.contains(event.target)) return;
    setNavOpen(false);
  });

  // Close on Escape
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setNavOpen(false);
  });
}

// Project thumbnails slider (homepage section)
const sliderTrack = document.querySelector('#projectSlider .project-slider__track');
const sliderDots = document.getElementById('sliderDots');

if (sliderTrack && sliderDots) {
  const slides = sliderTrack.querySelectorAll('.slide');
  const slideCount = slides.length;
  const autoAdvanceMs = 1500;

  let activeIndex = 0;
  let intervalId = null;

  const updateSlider = (index) => {
    activeIndex = index;
    sliderTrack.style.transform = `translateX(-${index * 100}%)`;

    const dots = sliderDots.querySelectorAll('.slider-dot');
    dots.forEach((dot, dotIndex) => {
      dot.classList.toggle('active', dotIndex === index);
    });
  };

  const nextSlide = () => {
    if (slideCount <= 1) return;
    const nextIndex = (activeIndex + 1) % slideCount;
    updateSlider(nextIndex);
  };

  const createDots = () => {
    sliderDots.textContent = '';
    for (let i = 0; i < slideCount; i += 1) {
      const dot = document.createElement('button');
      dot.type = 'button';
      dot.className = 'slider-dot';
      dot.addEventListener('click', () => {
        updateSlider(i);
        resetAutoAdvance();
      });
      sliderDots.appendChild(dot);
    }
  };

  const resetAutoAdvance = () => {
    if (intervalId) clearInterval(intervalId);
    if (slideCount <= 1) return;
    intervalId = setInterval(nextSlide, autoAdvanceMs);
  };

  createDots();
  updateSlider(0);
  resetAutoAdvance();

  const sliderContainer = document.getElementById('projectSlider');
  if (sliderContainer) {
    sliderContainer.addEventListener('mouseenter', () => {
      if (intervalId) clearInterval(intervalId);
    });
    sliderContainer.addEventListener('mouseleave', () => {
      resetAutoAdvance();
    });
  }
}

// Per-project galleries (auto + arrows + thumbnails)
const galleries = Array.from(document.querySelectorAll('[data-gallery]'));
if (galleries.length) {
  const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const initGallery = (root) => {
    const track = root.querySelector('[data-gallery-track]');
    const slides = Array.from(root.querySelectorAll('[data-gallery-slide]'));
    if (!track || slides.length === 0) return;

    const prevBtn = root.querySelector('[data-gallery-prev]');
    const nextBtn = root.querySelector('[data-gallery-next]');
    const dotsRoot = root.querySelector('[data-gallery-dots]');
    const thumbs = Array.from(root.querySelectorAll('[data-gallery-thumb]'));
    const viewport = root.querySelector('[data-gallery-viewport]') || root;

    const slideCount = slides.length;
    let activeIndex = 0;
    let intervalId = null;

    const setIndex = (idx, opts = {}) => {
      const next = (idx % slideCount + slideCount) % slideCount;
      activeIndex = next;
      track.style.transform = `translateX(-${next * 100}%)`;

      if (dotsRoot) {
        const dots = Array.from(dotsRoot.querySelectorAll('.slider-dot'));
        dots.forEach((d, i) => d.classList.toggle('active', i === next));
      }

      if (thumbs.length) {
        thumbs.forEach((b, i) => b.classList.toggle('is-active', i === next));
      }

      if (opts.user) startAutoplay();
    };

    const buildDots = () => {
      if (!dotsRoot) return;
      dotsRoot.textContent = '';
      for (let i = 0; i < slideCount; i += 1) {
        const dot = document.createElement('button');
        dot.type = 'button';
        dot.className = 'slider-dot';
        dot.addEventListener('click', () => setIndex(i, { user: true }));
        dotsRoot.appendChild(dot);
      }
    };

    const stopAutoplay = () => {
      if (intervalId) clearInterval(intervalId);
      intervalId = null;
    };

    const startAutoplay = () => {
      stopAutoplay();
      if (prefersReducedMotion || slideCount <= 1) return;
      intervalId = setInterval(() => setIndex(activeIndex + 1), 2600);
    };

    if (prevBtn) prevBtn.addEventListener('click', () => setIndex(activeIndex - 1, { user: true }));
    if (nextBtn) nextBtn.addEventListener('click', () => setIndex(activeIndex + 1, { user: true }));

    thumbs.forEach((btn) => {
      const idx = Number(btn.dataset.galleryIndex) || 0;
      btn.addEventListener('click', () => setIndex(idx, { user: true }));
    });

    // Swipe support
    let startX = 0;
    let pointerDown = false;
    viewport.addEventListener('pointerdown', (e) => {
      if (slideCount <= 1) return;
      pointerDown = true;
      startX = e.clientX;
      try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    });
    viewport.addEventListener('pointerup', (e) => {
      if (!pointerDown) return;
      pointerDown = false;
      const dx = e.clientX - startX;
      if (Math.abs(dx) > 45) setIndex(activeIndex + (dx < 0 ? 1 : -1), { user: true });
    });
    viewport.addEventListener('pointercancel', () => { pointerDown = false; });

    root.addEventListener('mouseenter', stopAutoplay);
    root.addEventListener('mouseleave', startAutoplay);

    buildDots();
    setIndex(0);
    startAutoplay();

    if (slideCount <= 1) {
      if (prevBtn) prevBtn.style.display = 'none';
      if (nextBtn) nextBtn.style.display = 'none';
      if (dotsRoot) dotsRoot.style.display = 'none';
    }
  };

  galleries.forEach(initGallery);
}

// Stats count-up (runs once per section when visible)
const statsRoots = Array.from(document.querySelectorAll('[data-stats]'));
if (statsRoots.length) {
  const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const runCountup = (root) => {
    const counters = Array.from(root.querySelectorAll('[data-countup]'));
    counters.forEach((el) => {
      if (el.dataset.countupDone === 'true') return;
      el.dataset.countupDone = 'true';

      const target = Number(el.getAttribute('data-countup')) || 0;
      if (prefersReducedMotion) {
        el.textContent = String(target);
        return;
      }

      const durationMs = 900;
      const start = performance.now();

      const tick = (now) => {
        const t = Math.min(1, (now - start) / durationMs);
        // easeOutCubic
        const eased = 1 - Math.pow(1 - t, 3);
        const value = Math.round(eased * target);
        el.textContent = String(value);
        if (t < 1) requestAnimationFrame(tick);
      };

      requestAnimationFrame(tick);
    });
  };

  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          runCountup(entry.target);
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15, rootMargin: '80px 0px' });

    statsRoots.forEach((root) => io.observe(root));
  } else {
    statsRoots.forEach((root) => runCountup(root));
  }

  // In case the section is already visible on load (or the observer doesn't fire reliably),
  // eagerly run countup for any stats blocks currently in the viewport.
  statsRoots.forEach((root) => {
    const rect = root.getBoundingClientRect();
    if (rect.top < window.innerHeight && rect.bottom > 0) runCountup(root);
  });
}

// Smooth-scroll to hash targets after navigation (e.g. /#contact from other pages).
// Browsers often jump instantly on load; this replays the scroll smoothly once layout is ready.
(() => {
  const hash = window.location.hash;
  if (!hash) return;

  const target = document.querySelector(hash);
  if (!target) return;

  window.addEventListener('load', () => {
    // Reset first so the movement is visible and feels intentional.
    window.scrollTo({ top: 0, behavior: 'auto' });
    requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
})();
