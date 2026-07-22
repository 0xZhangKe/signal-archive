const PAGE_SIZE = 60;
const DEFAULT_LEFT_RATIO = 0.18;
const DEFAULT_MIDDLE_RATIO = 0.25;
const MIN_LEFT_WIDTH = 180;
const MIN_MIDDLE_WIDTH = 260;
const MIN_READER_WIDTH = 360;
const RESIZE_STEP = 16;

const state = {
  navigation: [],
  activeNode: null,
  activeKey: null,
  articles: [],
  activeArticleId: null,
  visibleCount: PAGE_SIZE,
};

const elements = {
  desk: document.querySelector(".archive-desk"),
  catalog: document.querySelector("#catalog"),
  sourceCount: document.querySelector("#source-count"),
  archiveStatus: document.querySelector("#archive-status"),
  listTitle: document.querySelector("#list-title"),
  articleCount: document.querySelector("#article-count"),
  articleList: document.querySelector("#article-list"),
  loadMore: document.querySelector("#load-more"),
  readerEmpty: document.querySelector("#reader-empty"),
  readerContent: document.querySelector("#reader-content"),
  readerSource: document.querySelector("#reader-source"),
  readerTitle: document.querySelector("#reader-title"),
  readerDate: document.querySelector("#reader-date"),
  readerLink: document.querySelector("#reader-link"),
  readerBody: document.querySelector("#reader-body"),
  placeholder: document.querySelector("#placeholder-template"),
  mobileTabs: [...document.querySelectorAll(".mobile-tab")],
  resizers: [...document.querySelectorAll(".column-resizer")],
};

function nodeKey(node) {
  return node.feedPath ?? node.listPath;
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

function makeSourceButton(source) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "source-button";
  button.textContent = source.title;
  button.title = source.title;
  button.classList.toggle("is-active", state.activeKey === nodeKey(source));
  button.addEventListener("click", () => selectNode(source));
  return button;
}

function renderCatalog() {
  elements.catalog.replaceChildren();
  let sourceCount = 0;

  for (const item of state.navigation) {
    if (item.type !== "category") {
      sourceCount += 1;
      const row = document.createElement("div");
      row.className = "nav-row";
      row.classList.toggle("is-active", state.activeKey === nodeKey(item));
      const button = document.createElement("button");
      button.type = "button";
      button.className = "nav-select";
      button.textContent = item.title;
      button.addEventListener("click", () => selectNode(item));
      row.append(button);
      elements.catalog.append(row);
      continue;
    }

    sourceCount += item.sources.length;
    const group = document.createElement("div");
    group.className = "nav-group";
    const row = document.createElement("div");
    row.className = "nav-row";
    row.classList.toggle("is-active", state.activeKey === nodeKey(item));

    const select = document.createElement("button");
    select.type = "button";
    select.className = "nav-select";
    select.textContent = item.title;
    select.addEventListener("click", () => selectNode(item));

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "nav-toggle";
    toggle.setAttribute("aria-label", `Expand ${item.title}`);
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML = "<span>▶</span>";

    const sources = document.createElement("div");
    sources.className = "source-list";
    sources.hidden = true;
    for (const source of item.sources) sources.append(makeSourceButton(source));

    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      toggle.setAttribute("aria-label", `${expanded ? "Expand" : "Collapse"} ${item.title}`);
      sources.hidden = expanded;
    });

    row.append(select, toggle);
    group.append(row, sources);
    elements.catalog.append(group);
  }

  elements.sourceCount.textContent = `${sourceCount} SOURCES`;
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
  elements.articleList.replaceChildren();
  const shown = state.articles.slice(0, state.visibleCount);
  elements.articleCount.textContent = `${state.articles.length} ITEMS`;
  elements.loadMore.hidden = state.visibleCount >= state.articles.length;

  if (!shown.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = '<span class="empty-symbol">⌁</span><p>No articles are available in this selection.</p>';
    elements.articleList.append(empty);
    return;
  }

  for (const article of shown) {
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
}

async function selectNode(node) {
  state.activeNode = node;
  state.activeKey = nodeKey(node);
  state.activeArticleId = null;
  state.visibleCount = PAGE_SIZE;
  elements.listTitle.textContent = node.title;
  elements.articleCount.textContent = "…";
  elements.articleList.innerHTML = '<div class="loading-state"><p>Preparing article list…</p></div>';
  renderCatalog();
  setMobilePanel("list");

  try {
    const response = await fetch(`./${node.listPath}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (state.activeKey !== nodeKey(node)) return;
    state.articles = Array.isArray(data.items) ? data.items : [];
    renderArticles();
  } catch (error) {
    elements.articleList.innerHTML = `<div class="empty-state"><p>Unable to load articles: ${error.message}</p></div>`;
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
    const response = await fetch(`./${article.detailPath}`);
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
    const [navigationResponse, buildResponse] = await Promise.all([
      fetch("./data/navigation.json"),
      fetch("./data/build.json"),
    ]);
    if (!navigationResponse.ok) throw new Error(`HTTP ${navigationResponse.status}`);
    const navigation = await navigationResponse.json();
    const build = buildResponse.ok ? await buildResponse.json() : null;
    state.navigation = Array.isArray(navigation.items) ? navigation.items : [];
    renderCatalog();
    elements.archiveStatus.textContent = build
      ? `${build.articleCount} articles indexed${build.failedSourceCount ? ` · ${build.failedSourceCount} sources need attention` : ""}`
      : "Archive catalog ready";
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

elements.loadMore.addEventListener("click", () => {
  state.visibleCount += PAGE_SIZE;
  renderArticles();
});

for (const tab of elements.mobileTabs) {
  tab.addEventListener("click", () => setMobilePanel(tab.dataset.panel));
}

resetColumnWidths();
initialize();
