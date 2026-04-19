(function () {
  const MODE_KEY = 'gcs-theme-mode';
  const LIGHT_KEY = 'gcs-theme-light';
  const DARK_KEY = 'gcs-theme-dark';
  const THEME_MODES = new Set(['system', 'light', 'dark']);
  const LIGHT_THEMES = new Set(['vscode-light', 'quiet-light', 'cool-light', 'sandstone-light']);
  const DARK_THEMES = new Set(['vscode-dark', 'graphite-dark', 'midnight-dark', 'deep-forest-dark']);
  const themeMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  const state = {
    mode: 'system',
    lightTheme: 'vscode-light',
    darkTheme: 'vscode-dark',
  };

  function loadThemeState() {
    try {
      const storedMode = window.localStorage.getItem(MODE_KEY);
      const storedLight = window.localStorage.getItem(LIGHT_KEY);
      const storedDark = window.localStorage.getItem(DARK_KEY);
      state.mode = THEME_MODES.has(storedMode) ? storedMode : 'system';
      state.lightTheme = LIGHT_THEMES.has(storedLight) ? storedLight : 'vscode-light';
      state.darkTheme = DARK_THEMES.has(storedDark) ? storedDark : 'vscode-dark';
    } catch (_) {
      state.mode = 'system';
      state.lightTheme = 'vscode-light';
      state.darkTheme = 'vscode-dark';
    }
  }

  function resolvedMode() {
    if (state.mode === 'system') {
      return themeMedia?.matches ? 'dark' : 'light';
    }
    return state.mode;
  }

  function activeTheme() {
    return resolvedMode() === 'dark' ? state.darkTheme : state.lightTheme;
  }

  function applyTheme() {
    document.documentElement.dataset.themeMode = state.mode;
    document.documentElement.dataset.colorMode = resolvedMode();
    document.documentElement.dataset.theme = activeTheme();
  }

  function persistTheme() {
    try {
      window.localStorage.setItem(MODE_KEY, state.mode);
      window.localStorage.setItem(LIGHT_KEY, state.lightTheme);
      window.localStorage.setItem(DARK_KEY, state.darkTheme);
    } catch (_) {
      // Ignore storage failures.
    }
  }

  function themeLabel(themeName) {
    const labels = {
      system: 'System',
      light: 'Light',
      dark: 'Dark',
      'vscode-light': 'VS Code Light',
      'quiet-light': 'Quiet Light',
      'cool-light': 'Cool Light',
      'sandstone-light': 'Sandstone Light',
      'vscode-dark': 'VS Code Dark',
      'graphite-dark': 'Graphite Dark',
      'midnight-dark': 'Midnight Dark',
      'deep-forest-dark': 'Deep Forest Dark',
    };
    return labels[themeName] || themeName;
  }

  function initShell(options = {}) {
    loadThemeState();
    applyTheme();

    const page = options.page || document.body.dataset.page || '';
    const title = options.title || document.body.dataset.pageTitle || 'Remote Rover GCS';
    const subtitle = options.subtitle || document.body.dataset.pageSubtitle || '';

    document.body.classList.add('app-body');

    const shell = document.querySelector('[data-app-shell]');
    if (!shell) return;

    const header = document.createElement('header');
    header.className = 'app-header';
    header.innerHTML = `
      <div class="app-header-inner">
        <a class="app-brand" href="/">
          <span class="app-brand-kicker">Ground Control Station</span>
          <strong>Remote Rover GCS</strong>
        </a>
        <nav class="app-nav" aria-label="Primary">
          <a class="app-nav-link${page === 'dashboard' ? ' active' : ''}" href="/"${page === 'dashboard' ? ' aria-current="page"' : ''}>Dashboard</a>
          <a class="app-nav-link${page === 'replay' ? ' active' : ''}" href="/replay"${page === 'replay' ? ' aria-current="page"' : ''}>Replay</a>
          <a class="app-nav-link${page === 'settings' ? ' active' : ''}" href="/settings"${page === 'settings' ? ' aria-current="page"' : ''}>Settings</a>
        </nav>
      </div>
    `;

    shell.prepend(header);

    const intro = document.querySelector('[data-page-intro]');
    if (intro && !intro.children.length) {
      shell.classList.add('has-page-intro');
      intro.classList.add('page-intro');
      intro.innerHTML = `
        <div>
          <p class="page-kicker">${title}</p>
          <h2>${title}</h2>
          ${subtitle ? `<p class="page-lede">${subtitle}</p>` : ''}
        </div>
      `;
    }

    if (themeMedia) {
      const onThemeChange = () => {
        if (state.mode !== 'system') return;
        applyTheme();
      };
      if (typeof themeMedia.addEventListener === 'function') {
        themeMedia.addEventListener('change', onThemeChange);
      } else if (typeof themeMedia.addListener === 'function') {
        themeMedia.addListener(onThemeChange);
      }
    }
  }

  function getThemeState() {
    return {
      themeMode: state.mode,
      lightTheme: state.lightTheme,
      darkTheme: state.darkTheme,
      resolvedMode: resolvedMode(),
      activeTheme: activeTheme(),
    };
  }

  function setThemeMode(mode) {
    state.mode = THEME_MODES.has(mode) ? mode : 'system';
    applyTheme();
    persistTheme();
    return getThemeState();
  }

  function setLightTheme(theme) {
    state.lightTheme = LIGHT_THEMES.has(theme) ? theme : 'vscode-light';
    applyTheme();
    persistTheme();
    return getThemeState();
  }

  function setDarkTheme(theme) {
    state.darkTheme = DARK_THEMES.has(theme) ? theme : 'vscode-dark';
    applyTheme();
    persistTheme();
    return getThemeState();
  }

  window.GCSCommon = {
    initShell,
    getThemeState,
    setThemeMode,
    setLightTheme,
    setDarkTheme,
    themeLabel,
  };
}());
