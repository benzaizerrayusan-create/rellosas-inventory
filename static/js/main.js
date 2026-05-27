// ── Theme ──────────────────────────────────────────────────────────────────
const THEME_KEY = 'rellosas_theme';
const html = document.documentElement;

function applyTheme(dark) {
  html.setAttribute('data-theme', dark ? 'dark' : 'light');
  const tog = document.getElementById('themeToggle');
  if (tog) tog.checked = dark;
  localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  applyTheme(saved === 'dark');
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();

  // Theme toggle
  const tog = document.getElementById('themeToggle');
  if (tog) tog.addEventListener('change', () => applyTheme(tog.checked));

  function updateTopbarClock() {
    const el = document.getElementById('topbarClock');
    if (!el) return;
    const now = new Date();
    const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const date = now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    el.textContent = `${time} · ${date}`;
  }
  updateTopbarClock();
  setInterval(updateTopbarClock, 1000);

  // Sidebar hamburger
  const ham = document.getElementById('hamburger');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  if (ham && sidebar) {
    ham.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      overlay && overlay.classList.toggle('show');
    });
    overlay && overlay.addEventListener('click', () => {
      sidebar.classList.remove('open');
      overlay.classList.remove('show');
    });
  }

  // Stock adjusters
  document.querySelectorAll('[data-adjust]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const itemId = btn.dataset.itemId;
      const delta = parseInt(btn.dataset.adjust);
      const qtyEl = document.getElementById(`qty-${itemId}`);
      try {
        const res = await fetch(`/item/adjust/${itemId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ delta })
        });
        const data = await res.json();
        if (data.quantity !== undefined) {
          qtyEl.textContent = data.quantity;
          // Update badge color
          const row = btn.closest('tr');
          if (row) {
            const threshold = parseInt(row.dataset.threshold || 10);
            row.classList.toggle('low-stock', data.quantity <= threshold);
          }
        }
      } catch (e) { console.error(e); }
    });
  });

  // Delete confirm
  document.querySelectorAll('.delete-form').forEach(form => {
    form.addEventListener('submit', e => {
      if (!confirm('Delete this item? This cannot be undone.')) e.preventDefault();
    });
  });

  // Category filter (chips)
  document.querySelectorAll('.cat-chip[data-cat]').forEach(chip => {
    chip.addEventListener('click', () => {
      const url = new URL(window.location);
      const cat = chip.dataset.cat;
      if (cat === '') url.searchParams.delete('category');
      else url.searchParams.set('category', cat);
      window.location = url.toString();
    });
  });

  // Search live filter (debounce)
  const searchInput = document.getElementById('searchInput');
  if (searchInput) {
    let timeout;
    searchInput.addEventListener('input', () => {
      clearTimeout(timeout);
      timeout = setTimeout(() => {
        const url = new URL(window.location);
        if (searchInput.value) url.searchParams.set('search', searchInput.value);
        else url.searchParams.delete('search');
        window.location = url.toString();
      }, 500);
    });
  }

  // Sort select
  const sortSelect = document.getElementById('sortSelect');
  if (sortSelect) {
    sortSelect.addEventListener('change', () => {
      const url = new URL(window.location);
      url.searchParams.set('sort', sortSelect.value);
      window.location = url.toString();
    });
  }

  // Subtype logic for Rice category
  const catSelect = document.getElementById('categorySelect');
  const subtypeGroup = document.getElementById('subtypeGroup');
  const subtypeLabel = document.getElementById('subtypeLabel');
  if (catSelect && subtypeGroup) {
    function updateSubtype() {
      const opt = catSelect.options[catSelect.selectedIndex];
      const catName = opt ? opt.text.trim() : '';
      if (catName === 'Rice') {
        subtypeGroup.style.display = '';
        subtypeLabel.textContent = 'Rice Type (e.g. Sinandomeng, Jasmine, Dinorado)';
      } else if (catName === 'Flour') {
        subtypeGroup.style.display = '';
        subtypeLabel.textContent = 'Flour Type (e.g. All-Purpose, Bread, Cake)';
      } else {
        subtypeGroup.style.display = 'none';
      }
    }
    catSelect.addEventListener('change', updateSubtype);
    updateSubtype();
  }

  // Auto-dismiss flash messages
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(a => a.style.opacity = '0');
  }, 3500);
});
