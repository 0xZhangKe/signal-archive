const PAGE_SIZE = 60;

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
};

function nodeKey(node) {
  return node.feedPath ?? node.listPath;
}

function formatDate(value) {
  if (!value) return "日期未记录";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
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
    toggle.setAttribute("aria-label", `展开 ${item.title}`);
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML = "<span>▶</span>";

    const sources = document.createElement("div");
    sources.className = "source-list";
    sources.hidden = true;
    for (const source of item.sources) sources.append(makeSourceButton(source));

    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      toggle.setAttribute("aria-label", `${expanded ? "展开" : "收起"} ${item.title}`);
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
    empty.innerHTML = '<span class="empty-symbol">⌁</span><p>这个档案夹目前没有可展示的文章。</p>';
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
    summary.textContent = article.summary || "此条目没有提供摘要。";
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
  elements.articleList.innerHTML = '<div class="loading-state"><p>正在抽取档案卡片…</p></div>';
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
    elements.articleList.innerHTML = `<div class="empty-state"><p>文章列表加载失败：${error.message}</p></div>`;
  }
}

async function openArticle(article) {
  state.activeArticleId = article.id;
  renderArticles();
  elements.readerEmpty.hidden = true;
  elements.readerContent.hidden = false;
  elements.readerSource.textContent = article.sourceTitle;
  elements.readerTitle.textContent = article.title;
  elements.readerDate.textContent = "正在展开文章…";
  elements.readerBody.innerHTML = '<div class="loading-state"><p>正在展开纸页…</p></div>';
  elements.readerLink.hidden = !article.link;
  if (article.link) elements.readerLink.href = article.link;
  setMobilePanel("reader");

  try {
    const response = await fetch(`./${article.detailPath}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const detail = await response.json();
    if (state.activeArticleId !== article.id) return;
    elements.readerDate.textContent = formatDate(detail.publishedAt);
    elements.readerBody.innerHTML = detail.content || `<p>${detail.summary || "此条目没有提供正文。"}</p>`;
  } catch (error) {
    elements.readerDate.textContent = formatDate(article.publishedAt);
    elements.readerBody.textContent = `文章加载失败：${error.message}`;
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
      ? `${build.articleCount} 篇文章已编目${build.failedSourceCount ? ` · ${build.failedSourceCount} 个来源待修复` : ""}`
      : "档案目录已就绪";
  } catch (error) {
    elements.archiveStatus.textContent = `Catalog 加载失败：${error.message}`;
    elements.catalog.innerHTML = '<div class="empty-state"><p>暂时无法打开档案柜。</p></div>';
  }
}

elements.loadMore.addEventListener("click", () => {
  state.visibleCount += PAGE_SIZE;
  renderArticles();
});

for (const tab of elements.mobileTabs) {
  tab.addEventListener("click", () => setMobilePanel(tab.dataset.panel));
}

initialize();
