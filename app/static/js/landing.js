(() => {
  'use strict';

  const page = document.querySelector('.landing-page');
  if (!page) return;

  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  let scrollFrame = 0;
  let scrollTarget = null;

  const cancelScroll = () => {
    window.cancelAnimationFrame(scrollFrame);
    scrollFrame = 0;
    scrollTarget = null;
  };

  const scrollToTarget = (target) => {
    cancelScroll();
    const start = window.scrollY;
    const margin = parseFloat(window.getComputedStyle(target).scrollMarginTop) || 0;
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const destination = Math.max(0, Math.min(start + target.getBoundingClientRect().top - margin, maxScroll));
    const finish = () => {
      scrollFrame = 0;
      scrollTarget = null;
      // Match native anchor navigation so keyboard users continue at the destination.
      if (!target.hasAttribute('tabindex')) {
        target.setAttribute('tabindex', '-1');
        target.addEventListener('blur', () => target.removeAttribute('tabindex'), { once: true });
      }
      target.focus({ preventScroll: true });
    };

    if (Math.abs(destination - start) < 1) {
      window.scrollTo({ top: destination, behavior: 'instant' });
      finish();
      return;
    }

    scrollTarget = target;
    const duration = Math.min(1100, Math.max(550, Math.abs(destination - start) * 0.35));
    let startedAt;
    const animate = (time) => {
      startedAt ??= time;
      const progress = Math.min((time - startedAt) / duration, 1);
      const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2;
      // Explicit instant steps avoid starting a second CSS smooth scroll on every frame.
      window.scrollTo({ top: start + (destination - start) * eased, behavior: 'instant' });
      if (progress < 1) scrollFrame = window.requestAnimationFrame(animate);
      else finish();
    };
    scrollFrame = window.requestAnimationFrame(animate);
  };

  const resolveHashTarget = (trigger) => {
    const raw = trigger?.dataset?.scrollTo || (trigger?.tagName === 'A' ? trigger.getAttribute('href') : '');
    if (!raw) return null;
    const hash = raw.startsWith('/#') ? raw.slice(1) : raw;
    if (!hash.startsWith('#') || hash.length < 2) return null;
    const target = document.getElementById(hash.slice(1));
    return target && page.contains(target) ? { hash, target } : null;
  };

  page.addEventListener('click', (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const trigger = event.target.closest('a[href^="#"], a[href^="/#"], [data-scroll-to]');
    if (!trigger || trigger.classList.contains('landing-skip-link') || trigger.hasAttribute('download') || (trigger.target && trigger.target !== '_self')) return;
    const resolved = resolveHashTarget(trigger);
    if (!resolved) return;
    event.preventDefault();
    if (window.location.hash !== resolved.hash) window.history.pushState(null, '', resolved.hash);
    scrollToTarget(resolved.target);
  });
  ['wheel', 'touchstart', 'pointerdown'].forEach((type) => {
    window.addEventListener(type, cancelScroll, { passive: true });
  });
  window.addEventListener('keydown', (event) => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ', 'Escape'].includes(event.key)) {
      cancelScroll();
    }
  });
  window.addEventListener('popstate', cancelScroll);
  window.addEventListener('hashchange', cancelScroll);

  if (window.location.hash.length > 1) {
    const initialTarget = document.getElementById(window.location.hash.slice(1));
    if (initialTarget && page.contains(initialTarget)) {
      window.requestAnimationFrame(() => scrollToTarget(initialTarget));
    }
  }

  let revealObserver;

  const revealElements = (container = page) => {
    const elements = container.querySelectorAll('[data-landing-reveal]');
    if (motionPreference.matches || !('IntersectionObserver' in window)) {
      elements.forEach((element) => element.classList.add('is-visible'));
      return;
    }
    if (!revealObserver) {
      revealObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          entry.target.classList.toggle('is-in-view', entry.isIntersecting);
          entry.target.querySelectorAll('[data-landing-reveal]').forEach((element) => {
            element.classList.toggle('is-visible', entry.isIntersecting);
          });
        });
      }, { threshold: 0, rootMargin: '0px 0px -10px 0px' });
    }
    elements.forEach((element) => {
      const section = element.closest('section, footer');
      if (!section) {
        element.classList.add('is-visible');
        return;
      }
      element.classList.add('landing-reveal');
      element.classList.toggle('is-visible', section.classList.contains('is-in-view'));
      // Observe the stationary section so animated children cannot retrigger their own reveal.
      revealObserver.observe(section);
    });
  };

  motionPreference.addEventListener('change', () => {
    if (!motionPreference.matches) {
      revealElements();
      return;
    }
    if (scrollTarget) scrollToTarget(scrollTarget);
    revealObserver?.disconnect();
    page.querySelectorAll('[data-landing-reveal]').forEach((element) => element.classList.add('is-visible'));
  });
  revealElements();

  const header = page.querySelector('[data-landing-header]');
  const navToggle = page.querySelector('[data-landing-nav-toggle]');
  const navigation = page.querySelector('[data-landing-navigation]');
  const navLabel = page.querySelector('[data-landing-nav-label]');

  const setNavigationOpen = (open) => {
    navigation.dataset.open = String(open);
    navToggle.setAttribute('aria-expanded', String(open));
    navLabel.textContent = open ? 'Close menu' : 'Open menu';
  };

  if (header && navToggle && navigation && navLabel) {
    setNavigationOpen(false);
    header.classList.add('landing-header--enhanced');
    navToggle.hidden = false;
    navToggle.addEventListener('click', () => {
      setNavigationOpen(navToggle.getAttribute('aria-expanded') !== 'true');
    });
    navigation.addEventListener('click', (event) => {
      if (event.target.closest('a')) setNavigationOpen(false);
    });
    header.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && navToggle.getAttribute('aria-expanded') === 'true') {
        setNavigationOpen(false);
        navToggle.focus();
      }
    });
    window.matchMedia('(max-width: 760px)').addEventListener('change', () => setNavigationOpen(false));
  }

  const videoOpen = page.querySelector('[data-landing-video-open]');
  const videoDialog = page.querySelector('[data-landing-video-dialog]');
  if (videoOpen && videoDialog) {
    const videoClose = videoDialog.querySelector('[data-landing-video-close]');
    const videoFrame = videoDialog.querySelector('iframe[data-src]');
    videoOpen.addEventListener('click', () => {
      if (videoFrame) videoFrame.src = videoFrame.dataset.src;
      videoDialog.showModal();
    });
    videoClose?.addEventListener('click', () => videoDialog.close());
    videoDialog.addEventListener('click', (event) => {
      if (event.target === videoDialog) videoDialog.close();
    });
    videoDialog.addEventListener('close', () => {
      if (videoFrame) videoFrame.removeAttribute('src');
    });
  }

  const menu = page.querySelector('[data-landing-menu]');
  if (!menu) return;


  const status = menu.querySelector('[data-landing-menu-status]');
  const retry = menu.querySelector('[data-landing-menu-retry]');
  const grid = menu.querySelector('[data-landing-menu-grid]');
  const imgBase = (typeof window !== 'undefined' && window.SHIKA_IMG_BASE) || '/static/images';
  const placeholder = `${imgBase}/product-placeholder.svg`;
  let products = [];

  let loading = false;

  const createElement = (tag, className, text) => {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };

  const productImageUrl = (value) => {
    if (typeof value !== 'string' || !value.trim()) return placeholder;
    const raw = value.trim();
    const mapped = raw.startsWith('/static/images/') ? `${imgBase}/${raw.slice('/static/images/'.length)}` : raw;
    try {
      const url = new URL(mapped, window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : placeholder;
    } catch {
      return placeholder;
    }
  };

  const createProduct = (product, index) => {
    const item = createElement('li', 'landing-product');
    item.setAttribute('data-landing-reveal', '');
    item.style.setProperty('--landing-reveal-delay', `${index * 85}ms`);
    const article = document.createElement('article');
    const media = createElement('div', 'landing-product-image');
    const image = document.createElement('img');
    const imageUrl = productImageUrl(product.image_url);
    image.alt = product.name;
    image.width = 600;
    image.height = 600;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.referrerPolicy = 'no-referrer';
    if (imageUrl === placeholder) image.dataset.placeholder = '';
    image.addEventListener('error', () => {
      image.dataset.placeholder = '';
      image.src = placeholder;
    }, { once: true });
    image.src = imageUrl;
    media.append(image);

    const copy = createElement('div', 'landing-product-copy');
    if (product.category_name) copy.append(createElement('p', 'landing-product-category', product.category_name));
    copy.append(createElement('h3', 'landing-product-name', product.name));
    copy.append(createElement('p', 'landing-product-price', window.shikaFormatMoney(product.price)));
    article.append(media, copy);
    item.append(article);
    return item;
  };

  const renderProducts = () => {
    grid.replaceChildren(...products.map(createProduct));
    grid.hidden = products.length === 0;
    status.textContent = products.length === 0
      ? 'There are no coffees to display right now. Please check back soon.'
      : `${products.length} coffee ${products.length === 1 ? 'favorite' : 'favorites'} to discover. Enjoy your next cup in-store.`;
    revealElements(grid);
  };

  const loadMenu = async () => {
    if (loading) return;
    loading = true;
    retry.hidden = true;
    grid.hidden = true;
    grid.setAttribute('aria-busy', 'true');
    status.textContent = 'Loading our current menu…';
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);

    try {
      // Public browsing must not use the staff API helper or send staff tokens.
      const response = await fetch('/menu/products', {
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Menu request failed (${response.status})`);
      const data = await response.json();
      if (!Array.isArray(data) || !data.every((product) => (
        product && typeof product.name === 'string' && product.name.trim()
        && ['number', 'string'].includes(typeof product.price)
        && String(product.price).trim() !== ''
        && Number.isFinite(Number(product.price)) && Number(product.price) >= 0
      ))) throw new Error('Invalid menu response');

      products = data.map((product) => ({
        ...product,
        name: product.name.trim(),
        category_name: typeof product.category_name === 'string' ? product.category_name.trim() : '',
      }))
        .filter((product) => /coffee|espresso/i.test(product.category_name))
        .slice(0, 4);
      renderProducts();
    } catch {
      products = [];
      grid.replaceChildren();
      grid.hidden = true;
      status.textContent = 'We couldn’t load the menu right now. Please try again in a moment.';
      retry.hidden = false;
    } finally {
      window.clearTimeout(timeout);
      grid.setAttribute('aria-busy', 'false');
      loading = false;
    }
  };

  retry.addEventListener('click', loadMenu);
  loadMenu();
})();
