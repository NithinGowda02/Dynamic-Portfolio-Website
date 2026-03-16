// LEGACY SCRIPT (not loaded by templates/base.html)
// The app uses: static/js/main.js

const navToggle = document.getElementById('navToggle');
const navList = document.querySelector('.nav__list');

if (navToggle && navList) {
  navToggle.addEventListener('click', () => {
    navList.classList.toggle('open');
  });

  // Close mobile menu when clicking on a navigation link
  navList.addEventListener('click', (event) => {
    if (event.target.classList.contains('nav__link')) {
      navList.classList.remove('open');
    }
  });
}

// Project slider
const sliderTrack = document.querySelector('.project-slider__track');
const sliderDots = document.getElementById('sliderDots');

if (sliderTrack && sliderDots) {
  const slides = sliderTrack.querySelectorAll('.slide');
  const slideCount = slides.length;
  const autoAdvanceMs = 1500; // faster auto-advance for tighter pace

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
    const nextIndex = (activeIndex + 1) % slideCount;
    updateSlider(nextIndex);
  };

  const createDots = () => {
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
    if (intervalId) {
      clearInterval(intervalId);
    }
    intervalId = setInterval(nextSlide, autoAdvanceMs);
  };

  createDots();
  updateSlider(0);
  resetAutoAdvance();

  // Pause on hover
  const sliderContainer = document.querySelector('.project-slider');
  if (sliderContainer) {
    sliderContainer.addEventListener('mouseenter', () => {
      if (intervalId) clearInterval(intervalId);
    });
    sliderContainer.addEventListener('mouseleave', () => {
      resetAutoAdvance();
    });
  }
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
    }, { threshold: 0.25 });

    statsRoots.forEach((root) => io.observe(root));
  } else {
    statsRoots.forEach((root) => runCountup(root));
  }
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
