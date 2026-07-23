const DEFAULT_LEFT_RATIO = 0.18;
const DEFAULT_MIDDLE_RATIO = 0.25;
const MIN_LEFT_WIDTH = 220;
const MIN_MIDDLE_WIDTH = 260;
const MIN_READER_WIDTH = 360;
const RESIZE_STEP = 16;
const AUTO_LOAD_THRESHOLD = 320;
const THEME_STORAGE_KEY = "signal-archive-theme";

const state = {
  navigation: [],
  expandedNodeKeys: new Set(),
  activeNode: null,
  activeKey: null,
  articles: [],
  totalArticleCount: 0,
  pages: [],
  nextPageIndex: 0,
  loadingPage: false,
  pageError: null,
  selectionVersion: 0,
  activeArticleId: null,
};

const elements = {
  desk: document.querySelector(".archive-desk"),
  catalog: document.querySelector("#catalog"),
  fetchWindow: document.querySelector("#fetch-window"),
  sourceCount: document.querySelector("#source-count"),
  archiveStatus: document.querySelector("#archive-status"),
  listTitle: document.querySelector("#list-title"),
  listSourceLink: document.querySelector("#list-source-link"),
  articleCount: document.querySelector("#article-count"),
  articleList: document.querySelector("#article-list"),
  readerEmpty: document.querySelector("#reader-empty"),
  readerContent: document.querySelector("#reader-content"),
  readerSource: document.querySelector("#reader-source"),
  readerTitle: document.querySelector("#reader-title"),
  readerDate: document.querySelector("#reader-date"),
  readerLink: document.querySelector("#reader-link"),
  readerBody: document.querySelector("#reader-body"),
  placeholder: document.querySelector("#placeholder-template"),
  themeToggle: document.querySelector("#theme-toggle"),
  mobileTabs: [...document.querySelectorAll(".mobile-tab")],
  resizers: [...document.querySelectorAll(".column-resizer")],
};

function preferredTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function currentTheme() {
  return document.documentElement.dataset.theme || preferredTheme();
}

function updateThemeButton(theme) {
  const isDark = theme === "dark";
  const label = isDark ? "Switch to light mode" : "Switch to dark mode";
  elements.themeToggle.dataset.theme = theme;
  elements.themeToggle.setAttribute("aria-pressed", String(isDark));
  elements.themeToggle.setAttribute("aria-label", label);
  elements.themeToggle.title = label;
}

function setTheme(theme, { persist = true } = {}) {
  document.documentElement.dataset.theme = theme;
  updateThemeButton(theme);
  if (persist) localStorage.setItem(THEME_STORAGE_KEY, theme);
}

function initializeTheme() {
  const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  if (storedTheme === "light" || storedTheme === "dark") {
    setTheme(storedTheme, { persist: false });
  } else {
    updateThemeButton(preferredTheme());
  }
}

function nodeKey(node) {
  return node.originalUrl ?? node.pages?.[0] ?? `${node.type}:${node.title}`;
}

function countUniqueSources(nodes) {
  const keys = new Set();
  for (const node of nodes) {
    if (node.type === "category") {
      for (const source of node.children ?? []) keys.add(nodeKey(source));
    } else {
      keys.add(nodeKey(node));
    }
  }
  return keys.size;
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
}

function setMobilePanel(panel) {
  elements.desk.dataset.mobilePanel = panel;
  for (const tab of elements.mobileTabs) {
    tab.classList.toggle("is-active", tab.dataset.panel === panel);
  }
}

function formatSuccessRate(value) {
  const rate = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1;
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(rate);
}

function makeHealthDot(value) {
  if (!Number.isFinite(value)) return null;
  const rate = Math.min(1, Math.max(0, value));
  if (rate >= 1) return null;
  const redWeight = rate <= 0.3
    ? 100
    : rate >= 0.8
      ? 0
      : Math.round((1 - (rate - 0.3) / 0.5) * 100);
  const dot = document.createElement("span");
  dot.className = "health-dot";
  dot.style.setProperty("--health-red-weight", `${redWeight}%`);
  dot.setAttribute("aria-hidden", "true");
  return dot;
}

function setNavigationContent(button, title, sourceState = null) {
  const label = document.createElement("span");
  label.className = "nav-label";
  label.textContent = title;
  const dot = makeHealthDot(sourceState);
  button.replaceChildren(...(dot ? [dot, label] : [label]));
}

function setSourceNavigationContent(button, source) {
  if (source.type !== "rss" || !Number.isFinite(source.state)) {
    setNavigationContent(button, source.title);
    button.title = source.title;
    return;
  }
  const metric = formatSuccessRate(source.state);
  setNavigationContent(button, source.title, source.state);
  button.title = `${source.title} · Fetch success rate ${metric}`;
  button.setAttribute("aria-label", `${source.title}, fetch success rate ${metric}`);
}

function makeSourceButton(source) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "source-button";
  setSourceNavigationContent(button, source);
  button.classList.toggle("is-active", state.activeKey === nodeKey(source));
  button.addEventListener("click", () => selectNode(source));
  return button;
}

function renderCatalog() {
  elements.catalog.replaceChildren();

  for (const item of state.navigation) {
    if (item.type !== "category") {
      const row = document.createElement("div");
      row.className = "nav-row";
      row.classList.toggle("is-active", state.activeKey === nodeKey(item));
      const button = document.createElement("button");
      button.type = "button";
      button.className = "nav-select";
      setSourceNavigationContent(button, item);
      button.addEventListener("click", () => selectNode(item));
      row.append(button);
      elements.catalog.append(row);
      continue;
    }

    const childSources = Array.isArray(item.children) ? item.children : [];
    const itemKey = nodeKey(item);
    const isExpanded = state.expandedNodeKeys.has(itemKey);
    const group = document.createElement("div");
    group.className = "nav-group";
    group.classList.toggle("is-active", state.activeKey === itemKey);
    const row = document.createElement("div");
    row.className = "nav-row";
    row.classList.toggle("is-active", state.activeKey === nodeKey(item));

    const select = document.createElement("button");
    select.type = "button";
    select.className = "nav-select";
    setNavigationContent(select, item.title);
    select.title = item.title;
    select.setAttribute("aria-label", item.title);
    select.addEventListener("click", () => selectNode(item));

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "nav-toggle";
    toggle.setAttribute("aria-label", `${isExpanded ? "Collapse" : "Expand"} ${item.title}`);
    toggle.setAttribute("aria-expanded", String(isExpanded));
    toggle.innerHTML = "<span>▶</span>";

    const sources = document.createElement("div");
    sources.className = "source-list";
    sources.hidden = !isExpanded;
    for (const source of childSources) sources.append(makeSourceButton(source));

    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      if (expanded) {
        state.expandedNodeKeys.delete(itemKey);
      } else {
        state.expandedNodeKeys.add(itemKey);
      }
      toggle.setAttribute("aria-expanded", String(!expanded));
      toggle.setAttribute("aria-label", `${expanded ? "Expand" : "Collapse"} ${item.title}`);
      sources.hidden = expanded;
    });

    row.append(select, toggle);
    group.append(row, sources);
    elements.catalog.append(group);
  }

  elements.sourceCount.textContent = `${countUniqueSources(state.navigation)} SOURCES`;
}

function renderPlaceholder() {
  return elements.placeholder.content.firstElementChild.cloneNode(true);
}

function articleImage(article) {
  if (!article.image) return renderPlaceholder();
  const image = document.createElement("img");
  image.className = "article-thumb";
  image.src = article.image;
  image.alt = "";
  image.loading = "lazy";
  image.referrerPolicy = "no-referrer";
  image.addEventListener("error", () => image.replaceWith(renderPlaceholder()), { once: true });
  return image;
}

function renderArticles() {
  const previousScrollTop = elements.articleList.scrollTop;
  elements.articleList.replaceChildren();
  const hasMore = state.nextPageIndex < state.pages.length;
  const itemCount = Number.isInteger(state.totalArticleCount)
    ? state.totalArticleCount
    : `${state.articles.length}${hasMore ? "+" : ""}`;
  elements.articleCount.textContent = articleCountLabel(itemCount);

  if (!state.articles.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const symbol = document.createElement("span");
    symbol.className = "empty-symbol";
    symbol.textContent = "⌁";
    const message = document.createElement("p");
    message.textContent = state.pageError
      ? `Unable to load articles: ${state.pageError}`
      : "No articles are available in this selection.";
    empty.append(symbol, message);
    elements.articleList.append(empty);
    return;
  }

  for (const article of state.articles) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "article-card";
    card.classList.toggle("is-active", state.activeArticleId === article.id);
    card.append(articleImage(article));

    const copy = document.createElement("div");
    copy.className = "card-copy";
    const source = document.createElement("p");
    source.className = "card-source";
    source.textContent = `${article.sourceTitle} · ${formatDate(article.publishedAt)}`;
    const title = document.createElement("h3");
    title.className = "card-title";
    title.textContent = article.title;
    const summary = document.createElement("p");
    summary.className = "card-summary";
    summary.textContent = article.summary || "No summary was provided for this entry.";
    copy.append(source, title, summary);
    card.append(copy);
    card.addEventListener("click", () => openArticle(article));
    elements.articleList.append(card);
  }

  if (state.loadingPage || state.pageError) {
    const status = document.createElement("p");
    status.className = "pagination-status";
    status.textContent = state.loadingPage
      ? "Loading more articles…"
      : `Unable to load more articles: ${state.pageError}`;
    elements.articleList.append(status);
  }

  elements.articleList.scrollTop = previousScrollTop;
}

function articleListIsNearEnd() {
  const remainingScroll =
    elements.articleList.scrollHeight -
    elements.articleList.scrollTop -
    elements.articleList.clientHeight;
  return remainingScroll <= AUTO_LOAD_THRESHOLD;
}

function scheduleAutomaticPageLoad() {
  window.requestAnimationFrame(() => {
    if (!state.pageError && articleListIsNearEnd()) loadNextPage();
  });
}

function updateListTitle(node) {
  const sourceUrl = node.type !== "category" ? node.originalUrl : null;
  elements.listTitle.hidden = Boolean(sourceUrl);
  elements.listSourceLink.hidden = !sourceUrl;
  if (sourceUrl) {
    elements.listSourceLink.textContent = node.title;
    elements.listSourceLink.href = sourceUrl;
    elements.listSourceLink.title = `Open original feed: ${sourceUrl}`;
  } else {
    elements.listTitle.textContent = node.title;
    elements.listSourceLink.removeAttribute("href");
  }
}

function articleCountLabel(itemCount) {
  const node = state.activeNode;
  let status = "";
  if (node?.type === "category") {
    const failedCount = Number.isInteger(node.failed_count) ? node.failed_count : 0;
    status = `${failedCount} FAILED`;
  } else if (node?.type === "rss" && Number.isFinite(node.state)) {
    status = `${formatSuccessRate(node.state)} SUCCESS`;
  }
  return `${status ? `${status} · ` : ""}${itemCount} ITEMS`;
}

function updateFetchWindow(rendered) {
  const started = new Date(rendered.startedAt);
  if (Number.isNaN(started.valueOf())) {
    elements.fetchWindow.textContent = "No fetch history";
    elements.fetchWindow.removeAttribute("datetime");
    elements.fetchWindow.removeAttribute("title");
    return;
  }
  const dateTimeFormat = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  elements.fetchWindow.textContent = dateTimeFormat.format(started);
  elements.fetchWindow.dateTime = rendered.startedAt;
  elements.fetchWindow.removeAttribute("title");
}

async function selectNode(node, { showList = true } = {}) {
  state.activeNode = node;
  state.activeKey = nodeKey(node);
  state.selectionVersion += 1;
  state.activeArticleId = null;
  state.articles = [];
  state.totalArticleCount = Number.isInteger(node.articleCount) ? node.articleCount : null;
  state.pages = Array.isArray(node.pages) ? node.pages : [];
  state.nextPageIndex = 0;
  state.loadingPage = false;
  state.pageError = null;
  updateListTitle(node);
  elements.articleCount.textContent = state.totalArticleCount === null
    ? "…"
    : articleCountLabel(state.totalArticleCount);
  elements.articleList.scrollTop = 0;
  elements.articleList.innerHTML = '<div class="loading-state"><p>Preparing article list…</p></div>';
  renderCatalog();
  if (showList) setMobilePanel("list");

  if (!state.pages.length) {
    renderArticles();
    return;
  }
  await loadNextPage();
}

async function loadNextPage() {
  if (state.loadingPage || state.nextPageIndex >= state.pages.length) return;
  const activeKey = state.activeKey;
  const selectionVersion = state.selectionVersion;
  const pagePath = state.pages[state.nextPageIndex];
  state.loadingPage = true;
  state.pageError = null;
  if (state.articles.length) renderArticles();

  try {
    const response = await fetch(`./data/${pagePath}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (state.activeKey !== activeKey || state.selectionVersion !== selectionVersion) return;
    const nextItems = Array.isArray(data.items) ? data.items : [];
    const knownIds = new Set(state.articles.map((article) => article.id));
    state.articles.push(...nextItems.filter((article) => !knownIds.has(article.id)));
    state.nextPageIndex += 1;
  } catch (error) {
    if (state.activeKey === activeKey && state.selectionVersion === selectionVersion) {
      state.pageError = error.message;
    }
  } finally {
    if (state.activeKey === activeKey && state.selectionVersion === selectionVersion) {
      state.loadingPage = false;
      renderArticles();
      if (!state.pageError) scheduleAutomaticPageLoad();
    }
  }
}

async function openArticle(article) {
  state.activeArticleId = article.id;
  renderArticles();
  elements.readerEmpty.hidden = true;
  elements.readerContent.hidden = false;
  elements.readerSource.textContent = article.sourceTitle;
  elements.readerTitle.textContent = article.title;
  elements.readerDate.textContent = "Opening article…";
  elements.readerBody.innerHTML = '<div class="loading-state"><p>Opening page…</p></div>';
  elements.readerLink.hidden = !article.link;
  if (article.link) elements.readerLink.href = article.link;
  setMobilePanel("reader");

  try {
    const response = await fetch(`./data/${article.detailPath}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const detail = await response.json();
    if (state.activeArticleId !== article.id) return;
    elements.readerDate.textContent = formatDate(detail.publishedAt);
    elements.readerBody.innerHTML = detail.content || `<p>${detail.summary || "No article body was provided."}</p>`;
  } catch (error) {
    elements.readerDate.textContent = formatDate(article.publishedAt);
    elements.readerBody.textContent = `Unable to load article: ${error.message}`;
  }
}

async function initialize() {
  try {
    const response = await fetch("./data/rendered.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const rendered = await response.json();
    state.navigation = Array.isArray(rendered.children) ? rendered.children : [];
    updateFetchWindow(rendered);
    renderCatalog();
    const sourceCount = countUniqueSources(state.navigation);
    elements.archiveStatus.textContent = `${sourceCount} sources ready`;
    if (state.navigation.length) {
      await selectNode(state.navigation[0], { showList: false });
    }
  } catch (error) {
    elements.archiveStatus.textContent = `Unable to load catalog: ${error.message}`;
    elements.catalog.innerHTML = '<div class="empty-state"><p>The catalog is temporarily unavailable.</p></div>';
  }
}

function resizerWidth() {
  return elements.resizers.reduce(
    (total, resizer) => total + resizer.getBoundingClientRect().width,
    0,
  );
}

function currentColumnWidths() {
  const styles = getComputedStyle(elements.desk);
  const columns = styles.gridTemplateColumns.split(" ").map(Number.parseFloat);
  return { left: columns[0], middle: columns[2] };
}

function applyColumnWidths(left, middle) {
  const available = elements.desk.getBoundingClientRect().width - resizerWidth();
  const safeLeft = Math.max(
    MIN_LEFT_WIDTH,
    Math.min(left, available - MIN_MIDDLE_WIDTH - MIN_READER_WIDTH),
  );
  const safeMiddle = Math.max(
    MIN_MIDDLE_WIDTH,
    Math.min(middle, available - safeLeft - MIN_READER_WIDTH),
  );
  elements.desk.style.setProperty("--left-width", `${safeLeft}px`);
  elements.desk.style.setProperty("--middle-width", `${safeMiddle}px`);

  const total = elements.desk.getBoundingClientRect().width;
  elements.resizers[0]?.setAttribute("aria-valuenow", String(Math.round((safeLeft / total) * 100)));
  elements.resizers[1]?.setAttribute("aria-valuenow", String(Math.round(((safeLeft + safeMiddle) / total) * 100)));
}

function resetColumnWidths() {
  if (window.matchMedia("(max-width: 720px)").matches) return;
  const available = elements.desk.getBoundingClientRect().width - resizerWidth();
  applyColumnWidths(available * DEFAULT_LEFT_RATIO, available * DEFAULT_MIDDLE_RATIO);
}

function resizeFromKeyboard(resizer, direction) {
  const widths = currentColumnWidths();
  if (resizer.dataset.resizer === "left") {
    applyColumnWidths(widths.left + direction * RESIZE_STEP, widths.middle);
  } else {
    applyColumnWidths(widths.left, widths.middle + direction * RESIZE_STEP);
  }
}

for (const resizer of elements.resizers) {
  resizer.setAttribute("aria-valuemin", "0");
  resizer.setAttribute("aria-valuemax", "100");

  resizer.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const startX = event.clientX;
    const start = currentColumnWidths();
    resizer.classList.add("is-dragging");
    document.body.classList.add("is-resizing");
    resizer.setPointerCapture(event.pointerId);

    const move = (moveEvent) => {
      const delta = moveEvent.clientX - startX;
      if (resizer.dataset.resizer === "left") {
        applyColumnWidths(start.left + delta, start.middle);
      } else {
        applyColumnWidths(start.left, start.middle + delta);
      }
    };

    const stop = () => {
      resizer.classList.remove("is-dragging");
      document.body.classList.remove("is-resizing");
      resizer.removeEventListener("pointermove", move);
      resizer.removeEventListener("pointerup", stop);
      resizer.removeEventListener("pointercancel", stop);
    };

    resizer.addEventListener("pointermove", move);
    resizer.addEventListener("pointerup", stop);
    resizer.addEventListener("pointercancel", stop);
  });

  resizer.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      resizeFromKeyboard(resizer, event.key === "ArrowLeft" ? -1 : 1);
    }
    if (event.key === "Home") {
      event.preventDefault();
      resetColumnWidths();
    }
  });

  resizer.addEventListener("dblclick", resetColumnWidths);
}

elements.themeToggle.addEventListener("click", () => {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
});

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!document.documentElement.dataset.theme) updateThemeButton(preferredTheme());
});

elements.articleList.addEventListener("scroll", () => {
  if (articleListIsNearEnd()) loadNextPage();
}, { passive: true });

for (const tab of elements.mobileTabs) {
  tab.addEventListener("click", () => setMobilePanel(tab.dataset.panel));
}

initializeTheme();
resetColumnWidths();
initialize();
